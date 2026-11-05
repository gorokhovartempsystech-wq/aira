"""F3 real native opaque transport and adapter-shaped portable checks."""

import importlib
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_docx_analysis_runs_start import world as world
from test_docx_analysis_storage_codec import execution
from test_docx_analysis_supervisor_runtime import api, finished, submit, wait_for

from ara.config import DatabaseSettings
from ara.docx_analysis_worker.control import AttemptIdentity, Budget
from ara.docx_analysis_worker.supervisor import ledger


@pytest.mark.parametrize("kind", ["macos", "windows"])
def test_driver_shaped_adapter_capture_and_close_N04(tmp_path, monkeypatch, kind):
    m = importlib.import_module("ara.docx_analysis_worker.supervisor._" + kind + "_adapter")
    calls = []
    clock = SimpleNamespace(now_ns=lambda: time.monotonic_ns())

    class NativeOwner:
        def reserve_slot(self):
            return object()

        def release_slot(self, slot):
            calls.append("release")
            return True

        def close(self):
            calls.append("owner_close")

    class Driver:
        def view(self):
            return SimpleNamespace(
                phase="closed",
                stage="analyzing",
                error_code=None,
                cleanup_confirmed=True,
                resources_closed=True,
            )

        def candidate(self):
            calls.append("capture")
            return b"fixture-response"

        def close(self, timeout=5):
            assert timeout == 0
            calls.append("close")
            return True

        def renew(self, bound):
            return True

        def stop(self, reason):
            calls.append(reason)

    backend = SimpleNamespace(
        clock_factory=lambda: clock,
        acquire_owner=lambda root: NativeOwner(),
        start=lambda *a, **k: Driver(),
    )
    monkeypatch.setattr(m, "_backend", lambda: backend)
    platform = m.MacPlatform() if kind == "macos" else m.WindowsPlatform()
    owner = platform.acquire_owner(tmp_path)
    slot = platform.reserve_slot(owner)
    now = platform.clock()
    attempt = platform.launch(
        slot,
        AttemptIdentity(uuid4(), uuid4(), uuid4(), 1),
        Budget(now + 300_000_000_000, now + 15_000_000_000, now, 50_000_000),
        request=b"fixture-request",
        execution_spec=b"fixture-spec",
    )
    observed = platform.observe(attempt)
    assert observed.candidate == b"fixture-response" and observed.physical_confirmed
    closed = platform.close_attempt(attempt)
    assert closed.closed and closed.physical_confirmed
    assert calls.index("capture") < calls.index("close")
    assert platform.release_slot(owner, slot)
    platform.close_owner(owner)


@pytest.mark.parametrize("stop", [False, True])
@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_actual_native_opaque_payload_not_b1_N01_N02_N03(world, tmp_path, stop):
    w = world["scopes"]["own"]
    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )
    s = api().create_fixture_supervisor(
        settings=DatabaseSettings(world["engine"].url.render_as_string(hide_password=False)),
        user_id=w["runtime"].user_id,
        project_id=w["runtime"].project_id,
        installation_id=installation,
        root=tmp_path,
        execution=execution(),
    )
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        ticket = submit(s, world)
        if stop:
            s.stop(ticket)
        result = finished(s, ticket)
        assert (
            result.sql_state.summary.status == "failed"
            if not stop
            else (result.sql_state.summary.status in ("cancelled", "failed"))
        )
        if not stop:
            assert result.sql_state.error_code == "invalid_result"
        wait_for(lambda: ledger.read_fence(world["engine"]).phase == "clean")
    finally:
        assert s.shutdown(timeout=5)
