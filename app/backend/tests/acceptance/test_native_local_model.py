"""Real-mode dispatch and bounded Windows EOF/job-accounting behavior."""

import sys
from types import SimpleNamespace

import pytest
from test_docx_analysis_windows_io import io as io
from test_docx_analysis_windows_io import pair, reject

from tests.docx_documents.test_analysis_windows_guardian_edges import Endpoint, binding, part
from tests.docx_documents.test_analysis_windows_guardian_edges import fake as fake


def test_closed_pipe_at_read_submission_is_eof(io):
    p = pair(io)
    io.submission = 109
    result = p.reader.begin_read().poll()
    assert result.eof and result.data == b"" and result.count == 0
    assert p.reader.close() and p.writer.close()
    assert not io.live


def test_closed_pipe_at_write_submission_is_still_an_error(io):
    p = pair(io)
    io.submission = 109
    reject(lambda: p.writer.begin_write(b"hello"))
    assert p.reader.close() and p.writer.close()
    assert not io.live


@pytest.mark.parametrize("persistent", [False, True])
def test_job_accounting_settles_without_forging_cleanup(fake, monkeypatch, persistent):
    api, clock, owner, slot = fake
    m = part("_launch")
    monkeypatch.setattr(
        m,
        "create_pipe_pair",
        lambda **kw: SimpleNamespace(reader=Endpoint(api, "read"), writer=Endpoint(api, "write")),
    )

    class Event:
        def __init__(self):
            api.next += 1
            self.value = api.next

        def handle(self):
            return self.value

        def set(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(m, "create_event", Event)
    obj = m.prepare_fixture_guardian(
        slot, binding(), deadline_ns=20_000_000_000, lease_ns=10_000_000_000
    )
    obj.start()
    api.signalled, api.count = True, 1
    view = obj.poll_process()
    assert view.process_exited and not view.job_empty and not view.hard_fault
    assert not obj.finish_close()
    clock.value += 1_999_000_000
    assert not obj.poll_process().hard_fault
    clock.value += 2_000_000
    if not persistent:
        api.count = 0
    assert obj.poll_process().hard_fault is persistent
    assert any(c[0] == "kill_job" for c in api.calls) is persistent
    api.count = 0
    assert obj.finish_close()
    assert owner.release_slot(slot)


@pytest.mark.parametrize("fails", [False, True])
def test_native_dispatch_uses_fixed_bundle_and_restores_import_path(monkeypatch, fails):
    from ara.docx_analysis_worker import native_model

    before = list(sys.path)
    seen = []

    def run(request, **kw):
        seen.append((request, kw))
        assert sys.path[0] == str(native_model.bundle()[1])
        if fails:
            raise ValueError("synthetic")

    monkeypatch.setattr(native_model, "run", run)
    if fails:
        with pytest.raises(ValueError):
            native_model.run_native("request", lambda _: None)
    else:
        assert native_model.run_native("request", lambda _: None) == 0
    assert seen[0][1]["model_dir"] == native_model.bundle()[0]
    assert sys.path == before


def test_windows_supervisor_converts_path_at_native_boundary(monkeypatch, tmp_path):
    from ara.docx_analysis_worker.supervisor._windows_adapter import WindowsPlatform
    from ara.docx_analysis_worker.supervisor.platform import _NativePlatform

    seen = []
    sentinel = object()

    def acquire(self, root):
        seen.append(root)
        return sentinel

    monkeypatch.setattr(_NativePlatform, "acquire_owner", acquire)
    assert WindowsPlatform().acquire_owner(tmp_path) is sentinel
    assert seen == [str(tmp_path)]


@pytest.mark.parametrize("fixture", [False, True])
def test_pending_receipt_reports_selected_execution_kind(fixture):
    from uuid import uuid4

    from ara.docx_analysis_api._wire import receipt

    result = receipt(uuid4(), uuid4(), fixture=fixture)
    assert result["phase"] == "admitting"
    assert result["fixture"] is fixture
