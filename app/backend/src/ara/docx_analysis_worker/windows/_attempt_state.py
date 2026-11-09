"""Bounded actor mailboxes. Native calls and codecs always run outside this mutex."""

import threading

from ._driver_models import AttemptView


class State:
    def __init__(self, holder, binding, budget, frame, spec_sha, clock, *, fixture=True):
        self.fixture = fixture
        self.holder, self.binding, self.clock = holder, binding, clock
        self.deadline, self.lease, self.watermark = (
            budget.deadline_ns,
            budget.lease_ns,
            budget.last_ns,
        )
        self.frame, self.spec_sha = frame, spec_sha
        self.cv = threading.Condition(threading.Lock())
        self.gate = self.handoff = None
        self.stopped = self.hard = self.closing = self.released = False
        self.error = self.stage = self.observation = self.status = None
        self.command = self.reply = None
        self.control_eof = False
        self.permit_ready = self.transport_valid = self.natural = self.resources_closed = False
        self.blocked = False
        self.timed_out = self.request_complete = False
        self.threads, self.started = {}, {}
        self.done = dict.fromkeys(("launch", "control", "data"), False)
        self.quiescent = dict.fromkeys(("control", "data"), False)

    def _stop_locked(self, error, hard):
        signal = not self.stopped or hard and not self.hard
        self.stopped, self.hard = True, self.hard or hard
        if self.error is None and error is not None:
            self.error = error
        if self.command is not None and self.command.outcome == "pending":
            self.command.outcome = "cancelled"
        self.reply = None
        self.cv.notify_all()
        return signal

    def signal(self, needed):
        if needed:
            try:
                self.holder.request_stop(hard=self.hard)
            except Exception:
                with self.cv:
                    self._stop_locked("transport", True)

    def stop(self, error=None, hard=False):
        with self.cv:
            needed = self._stop_locked(error, hard)
        self.signal(needed)

    def tick(self):
        try:
            sample = self.clock.now_ns()
            if type(sample) is not int or not 0 <= sample < 2**63:
                raise ValueError()
        except Exception:
            self.stop("clock", True)
            return None
        with self.cv:
            now = self.watermark = max(self.watermark, sample)
            signal = False
            cmd = self.command
            if cmd is not None and cmd.outcome == "pending" and now >= cmd.cutoff:
                cmd.outcome = "rejected"
                signal = self._stop_locked("transport", True)
            if not self.stopped and now >= min(self.deadline, self.lease):
                signal = (
                    self._stop_locked("deadline" if now >= self.deadline else "lease", False)
                    or signal
                )
        self.signal(signal)
        return now

    def pause(self, seconds):
        with self.cv:
            self.cv.wait(seconds)

    def await_handoff(self):
        with self.cv:
            while self.handoff is None:
                self.cv.wait(0.05)
            return None if self.handoff == "failed" else self.handoff

    def proof_locked(self):
        o = self.observation
        return bool(
            o is not None
            and o.creation == "created"
            and o.process_exited
            and o.exit_code == 0
            and o.job_empty
            and not o.hard_fault
        )

    def cleanup_locked(self):
        return bool(
            self.proof_locked()
            and self.status is not None
            and self.status.values["cleanup_confirmed"]
        )

    def candidate_locked(self):
        return bool(
            self.permit_ready
            and self.transport_valid
            and self.cleanup_locked()
            and self.status.values["exit_kind"] == "clean"
            and self.status.values["exit_code"] == 0
            and self.reply is not None
            and not (self.stopped or self.hard or self.closing or self.error)
        )

    def view(self):
        with self.cv:
            o, status = self.observation, self.status
            unresolved = bool(
                o
                and (
                    o.creation == "unknown"
                    or o.creation == "created"
                    and o.process_exited
                    and not self.cleanup_locked()
                )
            )
            if self.blocked or unresolved or self.timed_out and not self.resources_closed:
                phase = "blocked"
            elif self.resources_closed and all(self.done.values()):
                phase = "closed"
            elif self.stopped or self.closing:
                phase = "stopping"
            else:
                phase = "running" if self.request_complete else "starting"
            return AttemptView(
                phase,
                self.stage,
                self.stopped,
                self.error,
                status.values["exit_kind"] if status else None,
                status.values["exit_code"] if status else None,
                self.cleanup_locked(),
                self.candidate_locked(),
                self.permit_ready,
                self.resources_closed,
                self.fixture,
            )


def close_endpoints(state, endpoints, owner):
    """Cancellation stays on the original actor, including after caller timeout."""
    pending = list(endpoints)
    while pending:
        for endpoint in tuple(pending):
            try:
                if endpoint.close():
                    pending.remove(endpoint)
            except Exception:
                state.stop("transport", True)
                if getattr(endpoint, "_close_failed", False):
                    with state.cv:
                        state.blocked = True
                    return False
        if pending:
            state.pause(0.01)
    with state.cv:
        state.quiescent[owner] = True
        state.cv.notify_all()
    return True
