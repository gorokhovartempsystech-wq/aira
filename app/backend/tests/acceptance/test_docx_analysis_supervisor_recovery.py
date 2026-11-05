"""F3 job bounds, publication ACK retention and restart barriers."""

import copy
import importlib
import time
from threading import Event, Thread
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_analysis_runs_start import start
from test_docx_analysis_runs_start import world as world
from test_docx_analysis_supervisor_runtime import make, submit, wait_for
from test_docx_analysis_supervisor_sql import armed

from ara.documents.storage import DocumentError
from ara.docx_analysis_worker.control import AttemptControl, AttemptIdentity, Budget
from ara.docx_analysis_worker.supervisor import ledger


def module(name):
    return importlib.import_module("ara.docx_analysis_worker.supervisor." + name)


def test_lane_busy_result_cell_and_baseexception_A03_A04():
    m = module("_jobs")
    wake, entered, release = Event(), Event(), Event()
    lane = m.Lane("test", wake)
    lane.start()

    def work():
        entered.set()
        assert release.wait(5)
        return 17

    try:
        lane.submit(1, work)
        assert entered.wait(2)
        assert lane.busy
        with pytest.raises(Exception):
            lane.submit(2, lambda: pytest.fail("overflow"))
        assert lane.take() is None
        release.set()
        cell = wait_for(lane.take)
        assert cell.generation == 1 and cell.value == 17 and cell.error is None
        assert not lane.busy

        def bad():
            raise KeyboardInterrupt("private callback error")

        lane.submit(2, bad)
        result = wait_for(lane.take)
        assert result.error == "internal_error" and "private" not in repr(result)
    finally:
        release.set()
        lane.close()
        lane.thread.join(3)
        assert not lane.thread.is_alive()


@pytest.mark.parametrize("outcome", ["unknown", "committed", "rolled_back", "terminal"])
def test_settle_lost_ack_retries_exact_pair_D08_D09(outcome):
    m = module("_publication")
    from ara.docx_analysis_runs.guarded_port import PublicationPort

    c = AttemptControl(AttemptIdentity(uuid4(), uuid4(), uuid4(), 1), Budget(300, 100, 0, 0))
    c.mark_child_closed(now_ns=0)
    token = c.reserve(now_ns=0)

    class Port(PublicationPort):
        calls = []

        def view(self):
            return c.view()

        def reserve(self):
            return token

        def settle(self, permit, *, outcome):
            self.calls.append(outcome)
            result = c.settle(permit, outcome=outcome, now_ns=1)
            if len(self.calls) == 1:
                raise DocumentError(409, "publication_in_progress", "busy", False)
            return result

    delegate = Port()
    port = m.WakePublicationPort(delegate, Event())
    with pytest.raises(DocumentError):
        port.settle(token, outcome=outcome)
    port.flush_settlement()
    assert delegate.calls == [outcome, outcome]
    assert port.pending is False
    if outcome != "unknown":
        assert port.resolved == (token, outcome)
    assert c.view().phase == (
        "succeeded"
        if outcome == "committed"
        else "unknown"
        if outcome == "unknown"
        else "terminal"
        if outcome == "terminal"
        else "open"
    )


def test_exit_authority_cannot_be_constructed_or_forged_D12(pg_engine):
    m = module("_exit_authority")
    with pytest.raises(TypeError):
        m.ExitAuthority()
    fake = object.__new__(m.ExitAuthority)
    with pytest.raises(Exception) as caught:
        module("_terminal").apply_exit(pg_engine, fake)
    assert caught.value.code in ("invalid_handle", "validation_error")
    with pytest.raises(TypeError):
        copy.copy(fake)


@pytest.mark.parametrize("mutation", ["unprovisioned", "missing", "wrong_installation", "armed"])
def test_startup_fail_closed_no_factory_E06_E09(world, tmp_path, mutation):
    if mutation == "armed":
        c, binding, row, runtime = armed(world)
        installation = binding.owner.installation_id
        s, p = make(world, tmp_path, provision=False, installation=installation)
    else:
        s, p = make(world, tmp_path, provision=mutation == "wrong_installation")
        if mutation == "missing":
            with world["engine"].begin() as conn:
                conn.execute(text("DELETE FROM docx_analysis_supervisor"))
        if mutation == "wrong_installation":
            s, p = make(world, tmp_path, provision=False, installation=uuid4())
    before = ledger.read_fence(world["engine"]) if mutation != "missing" else None
    try:
        s.start()
        wait_for(lambda: s.view().phase == "blocked")
        assert s.view().recovery_required and p.launches == 0
        with pytest.raises(module("runtime").SupervisorError):
            submit(s, world)
        if before is not None:
            assert ledger.read_fence(world["engine"]) == before
    finally:
        assert s.shutdown(timeout=5)


def test_startup_retires_old_queue_without_inference_E08(world, tmp_path):
    s, p = make(world, tmp_path)
    old = start(world)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        assert p.launches == 0
        with world["engine"].connect() as c:
            row = c.execute(
                text("SELECT status,error_code FROM docx_analysis_runs WHERE id=:r"),
                {"r": old.summary.run_id},
            ).one()
            assert tuple(row) == ("failed", "interrupted")
    finally:
        assert s.shutdown(timeout=5)


@pytest.mark.parametrize("success", [False, True])
def test_drained_restart_only_reconciles_E07_E10(world, tmp_path, success):
    from test_docx_analysis_lifecycle import body

    from ara.docx_analysis_runs import _lifecycle as old

    c, binding, row, runtime = armed(world)
    if success:
        assert old.complete_attempt(world["engine"], c, reply=body(c)).accepted
    else:
        old.fail_attempt(world["engine"], c, error_code="adapter_error")
    ledger.record_drained(world["engine"], binding=binding, expected_revision=row.revision)
    s, p = make(world, tmp_path, provision=False, installation=binding.owner.installation_id)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        assert p.launches == 0 and ledger.read_fence(world["engine"]).phase == "clean"
        with world["engine"].connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM docx_analysis_results")) == int(success)
    finally:
        assert s.shutdown(timeout=5)


def test_active_snapshot_rejects_multiple_old_running_E08(world, tmp_path):
    # Two independently owned scopes are legitimate old SQL history, not a valid S queue.
    from ara.docx_analysis_runs import claim_next

    s, p = make(world, tmp_path)
    start(world)
    start(world, "peer")
    assert claim_next(world["engine"], worker_instance_id=uuid4())
    assert claim_next(world["engine"], worker_instance_id=uuid4())
    try:
        s.start()
        wait_for(lambda: s.view().phase == "blocked")
        assert p.launches == 0
    finally:
        assert s.shutdown(timeout=5)


def test_real_dispatcher_port_uses_single_owner_A06():
    from ara.docx_analysis_worker.supervisor import create_dispatcher

    now = time.monotonic_ns()
    d = create_dispatcher(
        AttemptIdentity(uuid4(), uuid4(), uuid4(), 1),
        Budget(now + 300_000_000_000, now + 15_000_000_000, now, 50_000_000),
        clock=time.monotonic_ns,
    )
    d.post_child_closed()
    stop = Event()

    def owner():
        while not stop.is_set():
            d.step()
            stop.wait(0.002)

    t = Thread(target=owner)
    t.start()
    try:
        port = module("_publication").WakePublicationPort(d.publication_port(), Event())
        permit = port.reserve()
        assert permit is not None
        assert port.settle(permit, outcome="committed").phase == "succeeded"
    finally:
        stop.set()
        t.join(2)


def _isolated(world, root, case, connection):
    """Only synthetic test ports; child exit is never used as native recovery proof."""
    try:
        s, p = make(world, root)
        original = Thread.start
        if case.startswith("thread"):

            def fail(thread):
                if thread.name == "aira-supervisor-control":
                    if case == "thread_after":
                        original(thread)
                    raise RuntimeError("private start diagnostic")
                return original(thread)

            Thread.start = fail
            try:
                s.start()
            finally:
                Thread.start = original
            wait_for(lambda: s.view().phase == "blocked")
            assert p.trace == [] and p.launches == 0
            connection.send(True)
            return
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        if case == "release":
            p.release_result = False
        elif case == "factory":

            def broken(*a, **kw):
                p.launches += 1
                p.entered.set()
                raise RuntimeError("private create diagnostic")

            p.launch = broken
        elif case == "factory_pending":
            p.launch_gate.clear()
        elif case == "renew":
            p.done.clear()
            p.renew_result = False
        submit(s, world)
        assert p.entered.wait(8)
        if case == "factory_pending":
            assert not s.shutdown(timeout=0.02)
            assert ledger.read_fence(world["engine"]).phase == "armed"
            assert p.launches == 1
            p.launch_gate.set()
            p.done.set()
            assert s.shutdown(timeout=5)
        elif case == "renew":
            p.clock.advance(4_000_000_000)
            wait_for(lambda: any(isinstance(x, tuple) and x[0] == "renew" for x in p.trace))
            p.clock.advance(12_000_000_000)
            assert p.stopped.wait(5)
            assert p.launches == 1
        else:
            wait_for(lambda: s.view().phase == "blocked")
            expected = "drained" if case == "release" else "armed"
            assert ledger.read_fence(world["engine"]).phase == expected
            assert not s.shutdown(timeout=0.02)
            assert p.launches == 1
            if case == "release":
                assert p.releases == 2 and p.current_slot is None
        connection.send(True)
    except BaseException:
        connection.send(False)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "case", ["thread_before", "thread_after", "factory", "factory_pending", "release", "renew"]
)
def test_unknown_retention_in_isolated_process_A02_A04_C04_C07_E04_E11(world, tmp_path, case):
    import multiprocessing
    import sys

    if sys.platform == "win32":
        pytest.skip("isolated fork harness runs on macOS; Windows VM gate remains separate")
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_isolated, args=(world, tmp_path, case, child))
    process.start()
    child.close()
    try:
        assert parent.poll(20), "isolated retention scenario timed out"
        assert parent.recv(), case
        process.join(5)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()


def test_resolved_rollback_sql_terminal_is_separate_fact_D09_D11(world):
    from test_docx_analysis_lifecycle import body

    from ara.docx_analysis_runs import _lifecycle as old

    c, binding, row, runtime = armed(world)
    old.fail_attempt(world["engine"], c, error_code="adapter_error")
    state = module("_queries").closed_publication(
        world["engine"], c, outcome="rolled_back", reply=body(c)
    )
    assert state.summary.status == "failed"


def test_success_cannot_be_reclassified_as_rollback_D11(world):
    from test_docx_analysis_lifecycle import body

    from ara.docx_analysis_runs import _lifecycle as old

    c, binding, row, runtime = armed(world)
    assert old.complete_attempt(world["engine"], c, reply=body(c)).accepted
    with pytest.raises(Exception) as caught:
        module("_queries").closed_publication(
            world["engine"], c, outcome="rolled_back", reply=body(c)
        )
    assert caught.value.code == "recovery_required"
    assert ledger.read_fence(world["engine"]).phase == "armed"


def test_started_supervisor_cannot_be_replaced_A02(world, tmp_path):
    s, p = make(world, tmp_path)
    other, other_port = make(world, tmp_path, provision=False)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        assert s.start().phase == "ready"
        with pytest.raises(module("runtime").SupervisorError) as caught:
            other.start()
        assert caught.value.code == "busy"
        assert other_port.trace == []
    finally:
        assert s.shutdown(timeout=5)
        assert other.shutdown(timeout=0)


def test_corrupt_drained_success_never_clears_E10(world, tmp_path):
    from test_docx_analysis_lifecycle import body

    from ara.docx_analysis_runs import _lifecycle as old

    c, binding, row, runtime = armed(world)
    assert old.complete_attempt(world["engine"], c, reply=body(c)).accepted
    ledger.record_drained(world["engine"], binding=binding, expected_revision=row.revision)
    with world["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_analysis_results SET reply_data=:raw"), {"raw": b"bad"})
    s, p = make(world, tmp_path, provision=False, installation=binding.owner.installation_id)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "blocked")
        assert p.launches == 0 and ledger.read_fence(world["engine"]).phase == "drained"
    finally:
        assert s.shutdown(timeout=5)
