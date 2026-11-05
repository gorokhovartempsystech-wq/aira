"""Detached metadata and private per-generation state; no application setup."""

import os
from dataclasses import dataclass, field, replace
from uuid import uuid4
from weakref import WeakSet

from ara.docx_analysis_worker.control._models import Uncopyable

_CODES = frozenset(
    (
        "validation_error invalid_handle not_ready busy queue_full storage_unavailable "
        "storage_error clock_error runtime_unavailable recovery_required "
        "shutdown_pending internal_error"
    ).split()
)


class SupervisorError(Exception):
    def __init__(self, code="internal_error"):
        self.code = code if code in _CODES else "internal_error"
        super().__init__(self.code)


def detached(state):
    return None if state is None else replace(state, summary=replace(state.summary))


@dataclass(frozen=True, slots=True)
class SupervisorView:
    phase: str
    fixture: bool
    error_code: str | None
    queued_count: int
    active_run_id: object
    pending_lanes: tuple[str, ...]
    recovery_required: bool


@dataclass(frozen=True, slots=True)
class RunTicketView:
    phase: str
    run_id: object
    document_id: object
    stop_requested: bool
    stop_reason: str | None
    sql_state: object
    error_code: str | None


_KEY = object()
_TICKETS = WeakSet()


class RunTicket(Uncopyable):
    def __new__(cls, key=None):
        if key is not _KEY:
            raise TypeError("tickets are issued by a supervisor")
        return super().__new__(cls)

    def __init__(self, key):
        self._pid = os.getpid()
        _TICKETS.add(self)

    def __repr__(self):
        return "<RunTicket>"


@dataclass(eq=False, repr=False)
class Entry:
    key: object
    command: object
    encoded: object
    provider: object
    anchor: int
    deadline: int
    order: int
    ticket: object = field(default_factory=lambda: RunTicket(_KEY))
    generation: object = field(default_factory=uuid4)
    phase: str = "admitting"
    run_id: object = None
    state: object = None
    error: object = None
    intent: object = None
    reason: object = None
    sealed: bool = False
    authority: object = None
    claim: object = None
    attempt_id: object = field(default_factory=uuid4)
    worker_id: object = field(default_factory=uuid4)
    binding: object = None
    dispatcher: object = None
    port: object = None
    publisher: object = None
    native: object = None
    slot: object = None
    budget: object = None
    stage: str = "slot"
    entered_factory: bool = False
    physical: bool = False
    closed: bool = False
    candidate: object = None
    captured_ns: object = None
    native_lease: int = 0
    renew_bound: object = None
    lease_ticket: object = None
    hb_started: int = 0
    hb_due: int = 0
    observe_due: float = 0
    retry_at: float = 0
    backoff: float = 0.25
    stop_sent: bool = False
    drained: bool = False
    released: bool = False
    publication_started: bool = False
    publication_closed: bool = False
    terminal: bool = False
    snapshot: object = None

    def view(self):
        return RunTicketView(
            self.phase,
            self.run_id,
            self.command.document_id,
            bool(self.intent or self.reason),
            self.reason,
            detached(self.state),
            self.error,
        )

    def discard_payloads(self):
        self.provider = self.claim = self.publisher = self.port = self.native = None
        self.candidate = self.dispatcher = self.budget = self.authority = None
