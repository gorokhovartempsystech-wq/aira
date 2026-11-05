"""Durable native-file intents tested on disposable PostgreSQL only."""

from hashlib import sha256
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from ara.db import Base
from ara.documents.storage import DocumentError
from ara.docx_files import storage
from ara.docx_files.state import Observation, classify


@pytest.fixture
def file_doc(run_world):
    from test_docx_visible_word import source

    from ara.docx_documents.storage import import_docx

    runtime = run_world["runtimes"]["own"]
    doc = import_docx(runtime, document_id=uuid4(), title="Synthetic", data=source("plain"))
    return runtime, doc, run_world


def observe(doc, **changes):
    return Observation(
        path="/synthetic/original.docx", identity="inode:1;mtime:1", sha256=doc.current_sha256
    ).model_copy(update=changes)


def begin(runtime, doc, version, **changes):
    return storage.prepare(
        runtime,
        doc.document_id,
        operation_id=changes.pop("operation_id", uuid4()),
        expected_version=version,
        storage_revision=doc.storage_revision,
        source_sha256=doc.current_sha256,
        **changes,
    )


def test_head_schema(pg_engine):
    with pg_engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_bind_restart_and_confirmed_file_dirty(file_doc):
    rt, doc, _ = file_doc
    assert storage.read(rt, doc.document_id).dirty_for_file(doc.current_sha256)
    first = storage.attach(rt, doc.document_id, observe(doc))
    rt.engine.dispose()  # new physical connections, all state is in DB
    restored = storage.read(rt, doc.document_id)
    assert restored == first
    assert not restored.dirty_for_file(doc.current_sha256)
    assert restored.dirty_for_file(sha256(b"edited").hexdigest())
    assert storage.attach(rt, doc.document_id, observe(doc)) == restored
    with pytest.raises(DocumentError):
        storage.attach(rt, doc.document_id, observe(doc, identity="external"))


def test_crash_after_publish_and_lost_ack(file_doc):
    rt, doc, _ = file_doc
    op = uuid4()
    pending = begin(rt, doc, 0, operation_id=op, save_as="/synthetic/new.docx")
    assert pending.payload == doc.current_data
    rt.engine.dispose()
    assert storage.read(rt, doc.document_id) == pending
    assert begin(rt, doc, 0, operation_id=op, save_as="/synthetic/new.docx") == pending
    observed = observe(doc, path="/synthetic/new.docx")
    done = storage.finish(rt, doc.document_id, operation_id=op, observed=observed)
    assert done.payload is None and done.state.pending is None
    assert storage.finish(rt, doc.document_id, operation_id=op, observed=observed) == done
    assert done.state.binding.saved_revision == doc.storage_revision


def test_newer_internal_save_does_not_change_pending_bytes(file_doc):
    rt, doc, _ = file_doc
    op = uuid4()
    begin(rt, doc, 0, operation_id=op, save_as="/synthetic/new.docx")
    with rt.engine.begin() as conn:
        conn.execute(
            text("UPDATE docx_documents SET storage_revision=storage_revision+1 WHERE id=:id"),
            {"id": doc.document_id},
        )
    saved = storage.read(rt, doc.document_id)
    assert saved.payload == doc.current_data
    assert saved.state.pending.saved_revision == doc.storage_revision
    assert begin(rt, doc, 0, operation_id=op, save_as="/synthetic/new.docx") == saved


def test_conflict_keeps_payload_and_binding(file_doc):
    rt, doc, _ = file_doc
    binding = storage.attach(rt, doc.document_id, observe(doc))
    op = uuid4()
    pending = begin(rt, doc, binding.version, operation_id=op)
    external = observe(doc, sha256="a" * 64)
    assert classify(pending.state.pending, external) == "conflict"
    with pytest.raises(DocumentError):
        storage.finish(rt, doc.document_id, operation_id=op, observed=external)
    with pytest.raises(DocumentError):
        storage.abort(rt, doc.document_id, operation_id=op, observed=external)
    assert storage.read(rt, doc.document_id) == pending


def test_abort_absent_new_path_preserves_original(file_doc):
    rt, doc, _ = file_doc
    attached = storage.attach(rt, doc.document_id, observe(doc))
    op = uuid4()
    begin(rt, doc, attached.version, operation_id=op, save_as="/synthetic/copy.docx")
    aborted = storage.abort(rt, doc.document_id, operation_id=op, observed=None)
    assert aborted.state.binding == attached.state.binding
    assert aborted.payload is None
    with pytest.raises(DocumentError):
        storage.finish(rt, doc.document_id, operation_id=op, observed=observe(doc))


@pytest.mark.parametrize("case", ["foreign", "stale", "pending", "path", "hash"])
def test_rejections(file_doc, case):
    rt, doc, world = file_doc
    before = storage.read(rt, doc.document_id)
    with pytest.raises(DocumentError):
        if case == "foreign":
            storage.read(world["runtimes"]["foreign"], doc.document_id)
        elif case == "stale":
            begin(rt, doc, 4, save_as="/synthetic/new.docx")
        elif case == "pending":
            before = begin(rt, doc, 0, save_as="/synthetic/new.docx")
            begin(rt, doc, before.version, save_as="/synthetic/other.docx")
        elif case == "path":
            begin(rt, doc, 0, save_as="relative.docx")
        else:
            storage.attach(rt, doc.document_id, observe(doc, sha256="a" * 64))
    assert storage.read(rt, doc.document_id) == before


def test_private_repr(file_doc):
    rt, doc, _ = file_doc
    pending = begin(rt, doc, 0, save_as="/synthetic/PRIVATE.docx")
    assert "PRIVATE" not in repr(pending) + repr(pending.state) + str(pending.state.pending)


def test_concurrent_prepare_has_one_winner(file_doc):
    from concurrent.futures import ThreadPoolExecutor

    rt, doc, _ = file_doc

    def attempt(index):
        try:
            return begin(rt, doc, 0, save_as=f"/synthetic/{index}.docx")
        except DocumentError as exc:
            return exc.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(not isinstance(item, str) for item in results) == 1
    assert "file_version_conflict" in results


def test_downgrade_refuses_saved_associations(file_doc):
    from test_docx_analysis_storage_migrations import migrate_down

    rt, doc, _ = file_doc
    before = storage.attach(rt, doc.document_id, observe(doc))
    with pytest.raises(RuntimeError, match="Cannot remove"):
        migrate_down(rt.engine, "0013_docx_review_preferences")
    assert storage.read(rt, doc.document_id) == before


def test_pending_survives_real_reader_process(file_doc):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    rt, doc, _ = file_doc
    begin(rt, doc, 0, save_as="/synthetic/new.docx")
    script = """
import json,sys
from uuid import UUID
from sqlalchemy import create_engine
from ara.documents.runtime import DocumentRuntime
from ara.docx_files.storage import read
job=json.load(sys.stdin)
engine=create_engine(job['url'],hide_parameters=True)
r=read(DocumentRuntime(engine=engine,user_id=UUID(job['user']),project_id=UUID(job['project']),mode='local'),UUID(job['doc']))
assert r.state.pending.sha256==job['hash']
assert r.payload is not None
engine.dispose()
print('restored')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(
            dict(
                url=rt.engine.url.render_as_string(hide_password=False),
                user=str(rt.user_id),
                project=str(rt.project_id),
                doc=str(doc.document_id),
                hash=doc.current_sha256,
            )
        ),
        capture_output=True,
        text=True,
        timeout=15,
        env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src")),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "restored\n"


@pytest.mark.parametrize("after_publish", [False, True])
def test_coordinator_recovers_interrupted_write(file_doc, after_publish):
    from ara.docx_files.coordinator import resume

    rt, doc, _ = file_doc
    begin(rt, doc, 0, save_as="/synthetic/new.docx")

    class Files:
        current = None
        writes = 0
        broken = True

        def observe(self, path):
            return self.current

        def write(self, path, payload, expected):
            assert expected is None and self.current is None
            assert payload == doc.current_data
            self.writes += 1
            if after_publish or not self.broken:
                self.current = observe(doc, path=path)
            if self.broken:
                raise OSError("simulated interruption")

    files = Files()
    with pytest.raises(DocumentError):
        resume(rt, doc.document_id, files=files)
    assert storage.read(rt, doc.document_id).state.pending is not None
    files.broken = False
    restored = resume(rt, doc.document_id, files=files)
    assert restored.state.pending is None
    assert files.writes == (1 if after_publish else 2)
    assert resume(rt, doc.document_id, files=files) == restored
