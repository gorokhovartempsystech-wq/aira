"""One retained attempt generation; physical, SQL and permit facts stay distinct."""

import time
from dataclasses import replace
from threading import Lock
from uuid import uuid4

from ara.docx_analysis_runs import _lifecycle as old
from ara.docx_analysis_runs.guarded_publish import GuardedPublisher
from ara.docx_analysis_worker.control import AttemptIdentity, make_budget

from . import _queries, _terminal, ledger, lifecycle
from ._publication import WakePublicationPort
from .dispatcher import create_dispatcher
from .sql_models import LaunchBinding


def duration(value):
    return (value.days * 86400 + value.seconds) * 1_000_000_000 + value.microseconds * 1000


def claim_budget_start(started, received, receipt):
    sample = receipt.budget_started_ns
    if receipt.replayed or sample is None:
        return started
    if type(sample) is not int or not started <= sample <= received:
        raise ValueError("invalid claim clock sample")
    return sample


def claim_args(c, e):
    return dict(
        document_id=e.command.document_id,
        run_id=e.run_id,
        attempt_id=e.attempt_id,
        worker_instance_id=e.worker_id,
        owner=c.s._owner_binding,
    )


def terminal(e, state):
    e.state = state
    if state.summary.status in old.TERMINAL:
        e.terminal, e.phase = True, "finished"


def error(c, tag, e, cell):
    e.error = cell.error
    if tag in ("launch", "slot", "observe", "close_native", "stop_native", "renew", "release"):
        if e.intent is None:
            e.intent = "child"
        c.block("recovery_required")
        if tag == "launch":
            e.stage = "blocked"
        elif tag == "release":
            e.release_failed = True
        elif tag in ("observe", "close_native"):
            e.native_failed = True
        return
    c.storage_fault()
    if tag == "claim":
        e.stage = "resolve_claim"
    elif tag == "arm":
        e.stage = "resolve_arm"
    elif tag in ("publish", "resolve_publication"):
        e.pub_stage = "resolve"
    c.retry(e)


def result(c, tag, e, cell):
    if cell.error:
        error(c, tag, e, cell)
        return
    value = cell.value
    e.retry_at, e.backoff = 0, 0.25
    if tag == "slot":
        e.slot, e.stage = value, "claim"
        if e.reason:
            e.closed, e.physical, e.stage = True, True, "stopped"
    elif tag in ("claim", "resolve_claim"):
        terminal(e, value.state)
        e.claim = value.claim
        if value.claim is None:
            e.closed, e.physical, e.stage = True, True, "stopped"
            if not e.terminal and e.reason is None:
                e.intent = "storage"
        else:
            claim = value.claim
            e.binding = LaunchBinding(
                c.s._owner_binding,
                uuid4(),
                claim.document_id,
                claim.run_id,
                claim.attempt_id,
                claim.worker_instance_id,
                1,
            )
            if e.reason:
                e.closed, e.physical, e.stage = True, True, "stopped"
            else:
                now = c.sample()
                b = make_budget(
                    started_ns=claim_budget_start(e.claim_started, now, value),
                    received_ns=now,
                    remaining_deadline_ns=duration(claim.deadline_at - claim.claimed_at),
                    remaining_lease_ns=duration(claim.lease_expires_at - claim.claimed_at),
                )
                e.budget = replace(
                    b,
                    deadline_ns=min(b.deadline_ns, e.deadline),
                    lease_ns=min(b.lease_ns, e.deadline),
                )
                e.native_lease = e.budget.lease_ns
                e.dispatcher = create_dispatcher(
                    AttemptIdentity(claim.run_id, claim.attempt_id, claim.worker_instance_id, 1),
                    e.budget,
                    clock=c.s._platform.clock,
                )
                e.dispatcher.step()
                e.hb_due = now + 3_000_000_000
                e.stage = "arm"
    elif tag in ("arm", "resolve_arm"):
        c.fence = value
        if tag == "resolve_arm" and value.phase == "clean":
            e.closed, e.physical, e.stage = True, True, "stopped"
        elif value.phase == "armed" and value.binding == e.binding:
            e.stage = "launch"
            if e.reason:
                e.closed, e.physical, e.stage = True, True, "stopped"
        else:
            c.block("recovery_required")
    elif tag == "launch":
        e.native = value
        if value is None:
            e.closed, e.physical = True, True
        e.stage = "observe"
    elif tag == "observe":
        e.observe_due = time.monotonic() + 0.01
        e.physical = e.physical or value.physical_confirmed
        if e.physical:
            e.renew_bound = None
        if value.stage is not None and value.stage not in old.STAGES:
            e.intent = e.intent or "protocol"
        elif value.stage is not None:
            e.native_stage = value.stage
        if value.error_code:
            e.intent = e.intent or "child"
        if value.candidate is not None and e.candidate is None and not e.reason:
            view = e.dispatcher.step().control
            captured = value.captured_ns
            if (
                type(value.candidate) is bytes
                and type(captured) is int
                and e.budget.last_ns <= captured <= view.last_ns
                and captured < min(e.native_lease, e.budget.deadline_ns)
                and view.phase == "open"
                and not view.stop_requested
            ):
                e.candidate, e.captured_ns = value.candidate, captured
        # Process exit is not transport completion. Closing now can discard the
        # last result bytes while the native reader is still draining its pipes.
        # Native transport retains its bounded drain/error handling; Stop still wins.
        e.need_close = (e.physical and e.candidate is not None) or bool(e.reason)
    elif tag == "close_native":
        e.physical = e.physical or value.physical_confirmed
        if value.closed:
            if not e.physical:
                e.native_failed = True
                c.block("recovery_required")
            else:
                e.closed = True
                if e.candidate is None and not e.reason:
                    e.intent = e.intent or "child"
        e.need_close = False
        e.observe_due = time.monotonic() + 0.01
    elif tag == "stop_native":
        e.stop_sent = True
    elif tag == "renew":
        if value is not None:
            e.native_lease = value
            if e.renew_bound == value:
                e.renew_bound = None
        e.renew_at = time.monotonic() + 0.01
    elif tag == "heartbeat":
        terminal(e, value.state)
        if value.accepted and not e.reason and not e.terminal:
            e.lease_ticket = e.dispatcher.post_lease_ack(
                started_ns=e.hb_started,
                received_ns=c.sample(),
                remaining_lease_ns=duration(value.state.lease_expires_at - value.heartbeat_at),
            )
        elif not e.terminal:
            e.intent = e.intent or "storage"
    elif tag in ("publish", "resolve_publication"):
        terminal(e, value)
        if e.terminal or (e.port is not None and e.port.resolved is not None):
            e.publication_closed = True
            e.pub_stage = "closed"
        elif e.reason:
            view = e.dispatcher.view()
            if (
                not e.port.pending
                and not view.publication_pending
                and view.control.phase not in ("committing", "unknown")
            ):
                e.publication_closed = True
                e.pub_stage = "closed"
            else:
                e.pub_stage = "resolve"
        else:
            e.pub_stage = "retry"
            e.retry_at = time.monotonic() + 0.25
    elif tag == "exit":
        terminal(e, value)
        c.issuer.revoke(e.authority)
        e.publication_closed = True
    elif tag == "drained":
        c.fence, e.drained = value, True
    elif tag == "release":
        e.slot = None
        if value is not True:
            e.release_failed = True
            c.block("recovery_required")
        else:
            e.released = True
    elif tag == "clear":
        c.fence = value
        c.remove(e)


def start_publication(c, e):
    if e.reason or e.sealed or e.terminal or e.candidate is None or not e.closed:
        return
    view = e.dispatcher.view()
    if not view.control.child_closed or view.publication_pending:
        return
    if e.publisher is None:
        e.port = WakePublicationPort(e.dispatcher.publication_port(), c.s._wake)
        e.publisher = GuardedPublisher(c.s._engines.publication, e.claim, port=e.port)
    if getattr(e, "pub_stage", "new") in ("new", "retry"):
        c.submit("publication", "publish", lambda: e.publisher.complete(reply=e.candidate).state, e)
        e.publication_started = True
        e.pub_stage = "running"


def resolve_publication(c, e):
    if getattr(e, "pub_stage", None) != "resolve":
        return

    def resolve():
        e.port.flush_settlement()
        if e.port.resolved is not None:
            return _queries.closed_publication(
                c.s._engines.publication, e.claim, outcome=e.port.resolved[1], reply=e.candidate
            )
        return e.publisher.reconcile().state

    c.submit("publication", "resolve_publication", resolve, e)


def exit_ready(c, e):
    if not e.reason or e.terminal or e.state is None or time.monotonic() < e.retry_at:
        return
    if c.busy(e, "admission", "control", "publication"):
        return
    if e.stage in ("claim", "resolve_claim", "arm", "resolve_arm") and e is c.s._active:
        return
    if e.dispatcher is not None:
        view = e.dispatcher.view()
        if view.publication_pending or view.control.phase in ("committing", "unknown", "succeeded"):
            return
        if e.port is not None and e.port.pending:
            return
    if e.publisher is not None and not e.publication_closed:
        return
    e.sealed, e.publication_closed = True, True
    authority = c.issuer.issue(e)
    c.submit("control", "exit", lambda: _terminal.apply_exit(c.s._engines.control, authority), e)


def native(c, e):
    if e.native is None or e.closed or getattr(e, "native_failed", False):
        return
    if e.reason and not e.stop_sent:
        c.submit(
            "platform_control", "stop_native", lambda: c.s._platform.stop(e.native, e.reason), e
        )
    if not c.busy(e, "lifecycle") and time.monotonic() >= e.observe_due:
        if getattr(e, "need_close", False) and not c.busy(e, "platform_control"):
            c.submit("lifecycle", "close_native", lambda: c.s._platform.close_attempt(e.native), e)
        else:
            c.submit("lifecycle", "observe", lambda: c.s._platform.observe(e.native), e)
    if not e.reason and not e.physical:
        if c.sample() >= e.native_lease:
            e.intent = e.intent or "lease"
        elif (
            e.renew_bound is not None
            and not c.busy(e, "platform_control")
            and time.monotonic() >= getattr(e, "renew_at", 0)
        ):
            bound = e.renew_bound
            attempt = e.native

            def renew():
                return bound if c.s._platform.renew(attempt, bound) is True else None

            c.submit("platform_control", "renew", renew, e)


def finish(c, e):
    if not e.closed or not e.physical or c.busy(e, "lifecycle", "platform_control"):
        return
    if e.dispatcher is not None and not e.dispatcher.view().control.child_closed:
        e.dispatcher.post_child_closed()
        e.dispatcher.step()
    if c.fence.phase == "armed" and not e.drained:
        rev = c.fence.revision
        c.submit(
            "control",
            "drained",
            lambda: ledger.record_drained(
                c.s._engines.control, binding=e.binding, expected_revision=rev
            ),
            e,
        )
    if not e.terminal:
        return
    e.sealed = True
    if e.publisher is None:
        e.publication_closed = True
    if (
        not e.publication_closed
        or c.busy(e, "control", "publication", "admission")
        or getattr(e, "release_failed", False)
    ):
        return
    if c.fence.phase == "armed":
        return
    if not e.released:
        if e.slot is None:
            c.block("recovery_required")
        else:
            c.submit("lifecycle", "release", lambda: c.s._platform.release_slot(c.owner, e.slot), e)
    elif c.fence.phase == "drained":
        rev = c.fence.revision
        c.submit(
            "control",
            "clear",
            lambda: ledger.clear_drained(
                c.s._engines.control, binding=e.binding, expected_revision=rev
            ),
            e,
        )
    else:
        c.remove(e)


def drive(c):
    for e in c.entries():
        if e is not c.s._active and e.phase == "queued" and e.reason:
            exit_ready(c, e)
        if e is not c.s._active and e.terminal:
            c.remove(e)
    if c.s._active is None and not c.s._shutdown and not c.storage_broken and not c.s._quarantine:
        for e in c.entries():
            if e.phase == "queued" and not e.reason:
                with c.s._lock:
                    c.s._active, e.phase = e, "active"
                break
    e = c.s._active
    if e is None:
        return
    if time.monotonic() >= e.retry_at:
        if e.stage == "slot":
            c.submit("lifecycle", "slot", lambda: c.s._platform.reserve_slot(c.owner), e)
        elif e.stage == "claim":
            if e.reason:
                e.closed, e.physical, e.stage = True, True, "stopped"
            else:
                if not c.s._lanes["control"].busy and "control" not in c.s._pending:
                    e.claim_started = c.sample()
                c.submit(
                    "control",
                    "claim",
                    lambda: lifecycle.claim_exact(
                        c.runtime(), **claim_args(c, e), monotonic=c.s._platform.clock
                    ),
                    e,
                )
        elif e.stage == "resolve_claim":
            c.submit(
                "control",
                "resolve_claim",
                lambda: _queries.resolve_claim(c.runtime(), **claim_args(c, e)),
                e,
            )
        elif e.stage == "arm":
            if e.reason:
                e.closed, e.physical, e.stage = True, True, "stopped"
            else:
                rev = c.fence.revision
                c.submit(
                    "control",
                    "arm",
                    lambda: ledger.arm_launch(
                        c.runtime(), e.claim, binding=e.binding, expected_revision=rev
                    ),
                    e,
                )
        elif e.stage == "resolve_arm":
            c.submit("control", "resolve_arm", lambda: ledger.read_fence(c.s._engines.control), e)
        elif e.stage == "launch":
            if e.reason:
                e.closed, e.physical, e.stage = True, True, "stopped"
            else:
                if not hasattr(e, "launch_gate"):
                    e.launch_gate = Lock()

                def launch():
                    with e.launch_gate:
                        v = e.dispatcher.view()
                        now = c.s._platform.clock()
                        if (
                            e.intent
                            or v.stop_pending
                            or v.control.stop_requested
                            or now >= min(e.budget.deadline_ns, e.budget.lease_ns)
                        ):
                            return None
                        if e.entered_factory:
                            raise RuntimeError("launch already entered")
                        e.entered_factory = True
                    return c.s._platform.launch(
                        e.slot,
                        v.control.identity,
                        e.budget,
                        request=e.claim.attempt.request_data,
                        execution_spec=e.claim.source.execution_spec,
                    )

                c.submit("lifecycle", "launch", launch, e)
    if e.lease_ticket is not None:
        decision = e.dispatcher.take_lease_result(e.lease_ticket)
        if decision is not None:
            e.lease_ticket = None
            if decision.accepted and not e.physical:
                e.renew_bound = decision.lease_ns
    native(c, e)
    if (
        e.dispatcher is not None
        and not e.reason
        and not e.terminal
        and not e.sealed
        and c.fence.phase in ("armed", "drained")
        and e.lease_ticket is None
        and e.renew_bound is None
        and c.sample() >= e.hb_due
    ):
        e.hb_started = c.sample()
        if c.submit(
            "control",
            "heartbeat",
            lambda: lifecycle.heartbeat(
                c.runtime(),
                e.claim,
                owner=c.s._owner_binding,
                stage=getattr(e, "native_stage", None),
            ),
            e,
        ):
            e.hb_due = e.hb_started + 3_000_000_000
    if time.monotonic() >= e.retry_at:
        resolve_publication(c, e)
        start_publication(c, e)
        exit_ready(c, e)
        finish(c, e)
