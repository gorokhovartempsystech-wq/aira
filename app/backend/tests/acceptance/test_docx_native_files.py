"""Native Python files and SQL recovery with real synthetic DOCX bytes."""

import hashlib
import os
import traceback
from uuid import uuid4

import pytest
import test_docx_file_state as fixtures

from ara.documents.storage import DocumentError
from ara.docx_files import storage
from ara.docx_files.coordinator import resume
from ara.docx_files.native import NativeFileError, NativeFiles, destination

file_doc = fixtures.file_doc


def test_real_file_write_reopen_and_replace(tmp_path):
    files = NativeFiles()
    path = destination(tmp_path / "требования.docx")
    files.write(path, b"synthetic first", None)
    before, data = files.selected(path)
    assert data == b"synthetic first"
    files.write(path, b"synthetic second", before)
    assert files.selected(path)[1] == b"synthetic second"
    assert not list(tmp_path.glob(".aira-save-*"))


@pytest.mark.parametrize("case", ["changed", "missing", "symlink", "hardlink", "exists"])
def test_external_changes_are_not_overwritten(tmp_path, case):
    files = NativeFiles()
    path = tmp_path / "source.docx"
    path.write_bytes(b"original")
    before = files.observe(path)
    if case == "changed":
        path.write_bytes(b"external")
    elif case == "missing":
        path.unlink()
    elif case == "symlink":
        path.unlink()
        other = tmp_path / "other.docx"
        other.write_bytes(b"external")
        path.symlink_to(other)
    elif case == "hardlink":
        os.link(path, tmp_path / "alias.docx")
    with pytest.raises(NativeFileError):
        files.write(path, b"replacement", None if case == "exists" else before)
    if case != "missing":
        assert path.read_bytes() in (b"original", b"external")
    assert not list(tmp_path.glob(".aira-save-*"))


@pytest.mark.parametrize("call", ["write", "fsync", "replace"])
def test_prepublication_fault_preserves_source(tmp_path, monkeypatch, call):
    files = NativeFiles()
    path = tmp_path / "source.docx"
    path.write_bytes(b"original")
    before = files.observe(path)

    def broken(*args, **kwargs):
        raise OSError("PRIVATE file path")

    monkeypatch.setattr(os, call, broken)
    with pytest.raises(NativeFileError) as error:
        files.write(path, b"new", before)
    assert "PRIVATE" not in "".join(traceback.format_exception(error.value))
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob(".aira-save-*"))


def test_read_permission_error_is_not_absence(tmp_path, monkeypatch):
    path = tmp_path / "source.docx"
    path.write_bytes(b"original")

    def denied(*args, **kwargs):
        raise PermissionError("PRIVATE")

    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(NativeFileError, match="file_read_failed"):
        NativeFiles().observe(path)


def test_late_new_file_is_not_replaced(tmp_path, monkeypatch):
    files = NativeFiles()
    path = tmp_path / "new.docx"
    original = os.link

    def race(src, dst):
        path.write_bytes(b"external")
        return original(src, dst)

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(NativeFileError):
        files.write(path, b"mine", None)
    assert path.read_bytes() == b"external"


def test_real_docx_crash_after_publication(file_doc, tmp_path):
    rt, doc, _ = file_doc
    files = NativeFiles()
    path = destination(tmp_path / "saved.docx")
    operation = uuid4()
    storage.prepare(
        rt,
        doc.document_id,
        operation_id=operation,
        expected_version=0,
        storage_revision=doc.storage_revision,
        source_sha256=doc.current_sha256,
        save_as=path,
    )

    class CrashAfterWrite:
        observe = files.observe

        def write(self, *args):
            files.write(*args)
            raise OSError("crash after publication PRIVATE")

    with pytest.raises(DocumentError) as error:
        resume(rt, doc.document_id, files=CrashAfterWrite())
    assert "PRIVATE" not in "".join(traceback.format_exception(error.value))
    assert storage.read(rt, doc.document_id).payload == doc.current_data
    rt.engine.dispose()

    class ReadbackOnly:
        observe = NativeFiles().observe

        def write(self, *args):
            pytest.fail("Already published file must not be rewritten")

    finished = resume(rt, doc.document_id, files=ReadbackOnly())
    assert finished.state.pending is None
    assert files.selected(path)[1] == doc.current_data
    assert not finished.dirty_for_file(doc.current_sha256)


def test_conflict_can_save_exact_pending_bytes_elsewhere(file_doc, tmp_path):
    rt, doc, _ = file_doc
    files = NativeFiles()
    original = tmp_path / "original.docx"
    original.write_bytes(doc.current_data)
    attached = storage.attach(rt, doc.document_id, files.observe(original))
    pending = storage.prepare(
        rt,
        doc.document_id,
        operation_id=uuid4(),
        expected_version=attached.version,
        storage_revision=doc.storage_revision,
        source_sha256=doc.current_sha256,
    )
    original.write_bytes(b"external edit")
    with pytest.raises(DocumentError):
        resume(rt, doc.document_id, files=files)
    target = destination(tmp_path / "copy.docx")
    redirected = storage.retarget(
        rt, doc.document_id, expected_version=pending.version, operation_id=uuid4(), path=target
    )
    assert redirected.payload == doc.current_data
    finished = resume(rt, doc.document_id, files=files)
    assert finished.state.binding.observed.path == target
    assert original.read_bytes() == b"external edit"
    assert (tmp_path / "copy.docx").read_bytes() == doc.current_data
    assert hashlib.sha256(doc.current_data).hexdigest() == finished.state.binding.observed.sha256


def test_postpublication_sync_is_uncertain(tmp_path, monkeypatch):
    files = NativeFiles()
    path = tmp_path / "new.docx"
    original, count = os.fsync, 0

    def sync(fd):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("PRIVATE directory error")
        return original(fd)

    if os.name == "nt":
        pytest.skip("POSIX directory fsync")
    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(NativeFileError, match="file_write_uncertain"):
        files.write(path, b"confirmed payload", None)
    assert path.read_bytes() == b"confirmed payload"


def test_actual_pending_file_written_by_new_process(file_doc, tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    rt, doc, _ = file_doc
    target = destination(tmp_path / "restart.docx")
    storage.prepare(
        rt,
        doc.document_id,
        operation_id=uuid4(),
        expected_version=0,
        storage_revision=doc.storage_revision,
        source_sha256=doc.current_sha256,
        save_as=target,
    )
    script = """
import json,sys
from uuid import UUID
from sqlalchemy import create_engine
from ara.documents.runtime import DocumentRuntime
from ara.docx_files.coordinator import resume
from ara.docx_files.native import NativeFiles
job=json.load(sys.stdin)
engine=create_engine(job['url'],hide_parameters=True)
rt=DocumentRuntime(engine=engine,user_id=UUID(job['user']),project_id=UUID(job['project']),mode='local')
r=resume(rt,UUID(job['doc']),files=NativeFiles())
assert r.state.pending is None
engine.dispose()
print('saved')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(
            dict(
                url=rt.engine.url.render_as_string(hide_password=False),
                user=str(rt.user_id),
                project=str(rt.project_id),
                doc=str(doc.document_id),
            )
        ),
        capture_output=True,
        text=True,
        timeout=15,
        env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src")),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "saved\n"
    assert Path(target).read_bytes() == doc.current_data
    assert storage.read(rt, doc.document_id).state.pending is None


def test_failed_close_does_not_retry_a_reused_descriptor(tmp_path, monkeypatch):
    import tempfile

    path = tmp_path / "target.docx"
    path.write_bytes(b"original")
    files = NativeFiles()
    before = files.observe(path)
    real_close, real_mkstemp = os.close, tempfile.mkstemp
    temporary_fd, replacement_fd = None, None

    def mkstemp(*args, **kwargs):
        nonlocal temporary_fd
        fd, name = real_mkstemp(*args, **kwargs)
        temporary_fd = fd
        return fd, name

    def close(fd):
        nonlocal replacement_fd
        if fd == temporary_fd and replacement_fd is None:
            real_close(fd)
            replacement_fd = os.open(tmp_path / "unrelated", os.O_CREAT | os.O_RDWR, 0o600)
            assert replacement_fd == fd
            raise InterruptedError("synthetic close uncertainty")
        real_close(fd)

    monkeypatch.setattr(tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(os, "close", close)
    try:
        with pytest.raises(NativeFileError):
            files.write(path, b"replacement", before)
        assert replacement_fd is not None
        os.fstat(replacement_fd)  # still owned by the unrelated operation
        assert path.read_bytes() == b"original"
    finally:
        if replacement_fd is not None:
            real_close(replacement_fd)
