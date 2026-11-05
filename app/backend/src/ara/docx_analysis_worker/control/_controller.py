"""Short locked transitions only: no clock reads, I/O or external callbacks."""

from threading import Lock

from ._budget import LEASE, identity_values, integer, total, validate_budget
from ._models import AttemptIdentity, ControlError, ControlView, Uncopyable, new_permit

REASONS = frozenset(
    ("user", "deadline", "lease", "clock", "storage", "child", "shutdown", "protocol")
)
OUTCOMES = frozenset(("committed", "rolled_back", "unknown", "terminal"))
FINAL = frozenset(("succeeded", "terminal"))


class AttemptControl(Uncopyable):
    __slots__ = (
        "_identity",
        "_deadline",
        "_lease",
        "_last",
        "_guard",
        "_phase",
        "_stop",
        "_reason",
        "_closed",
        "_token",
        "_outcome",
        "_lock",
    )

    def __init__(self, identity, budget):
        self._identity = identity_values(identity)
        self._deadline, self._lease, self._last, self._guard = validate_budget(budget)
        self._phase, self._stop, self._reason = "open", False, None
        self._closed, self._token, self._outcome = False, None, None
        self._lock = Lock()
        self._advance(self._last)

    def __repr__(self):
        return "<AttemptControl>"

    def _view(self):
        return ControlView(
            AttemptIdentity(*self._identity),
            self._phase,
            self._stop,
            self._reason,
            self._closed,
            self._deadline,
            self._lease,
            self._last,
        )

    def _stop_for(self, reason):
        if self._phase in FINAL:
            return
        if not self._stop:
            self._stop, self._reason = True, reason
        if self._phase == "open":
            self._phase = "stopped"

    def _advance(self, now):
        if self._phase in FINAL:
            return
        if now < self._last:
            self._stop_for("clock")
            return
        self._last = now
        if now >= self._deadline:
            self._stop_for("deadline")
        elif now >= self._lease:
            self._stop_for("lease")

    def view(self):
        with self._lock:
            return self._view()

    def tick(self, *, now_ns):
        integer(now_ns)
        with self._lock:
            self._advance(now_ns)
            return self._view()

    def request_stop(self, *, now_ns, reason="user"):
        integer(now_ns)
        if type(reason) is not str or reason not in REASONS:
            raise ControlError()
        with self._lock:
            self._advance(now_ns)
            self._stop_for(reason)
            return self._view()

    def acknowledge_lease(self, *, started_ns, received_ns, remaining_lease_ns):
        s, r = integer(started_ns), integer(received_ns)
        duration = integer(remaining_lease_ns, LEASE, 1)
        bound = total(s, duration)
        if r < s:
            raise ControlError()
        with self._lock:
            self._advance(r)
            if self._phase == "open":
                self._lease = min(self._deadline, max(s, bound - self._guard))
                if r >= self._lease:
                    self._stop_for("lease")
            return self._view()

    def mark_child_closed(self, *, now_ns):
        integer(now_ns)
        with self._lock:
            self._advance(now_ns)
            self._closed = True
            return self._view()

    def reserve(self, *, now_ns):
        integer(now_ns)
        with self._lock:
            self._advance(now_ns)
            if self._phase != "open" or self._stop or not self._closed:
                return None
            self._token, self._outcome = new_permit(), None
            self._phase = "committing"
            return self._token

    def settle(self, permit, *, outcome, now_ns):
        integer(now_ns)
        if type(outcome) is not str or outcome not in OUTCOMES:
            raise ControlError()
        with self._lock:
            if permit is None or permit is not self._token:
                raise ControlError("invalid_permit")
            # A resolved fact is immutable. Replayed delivery cannot change time or phase.
            if self._outcome in ("committed", "rolled_back", "terminal"):
                if outcome not in (self._outcome, "unknown"):
                    raise ControlError("conflicting_outcome")
                return self._view()
            if outcome == "committed":
                self._last = max(self._last, now_ns)
                self._phase = "succeeded"
            else:
                self._advance(now_ns)
                if outcome == "unknown":
                    self._phase = "unknown"
                elif outcome == "terminal":
                    self._phase = "terminal"
                else:
                    self._phase = "stopped" if self._stop else "open"
            self._outcome = outcome
            return self._view()
