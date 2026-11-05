"""Explicit fixture-only supervisor API. Import/construction never starts work."""

import math
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from uuid import UUID, uuid4
from weakref import WeakSet

from ara.config import DatabaseSettings
from ara.docx_analysis.storage_codec import (
    ExecutionSpec,
    RetryCheckCommand,
    SavedCheckCommand,
    encode_execution,
)
from ara.docx_analysis.visible_lists._models import PROFILE as LIST_PROFILE
from ara.docx_analysis.visible_main._models import PROFILE
from ara.docx_analysis.visible_outline._models import PROFILE as OUTLINE_PROFILE
from ara.docx_analysis.visible_style_lists._models import PROFILE as STYLE_LIST_PROFILE
from ara.docx_analysis.visible_word._models import PROFILE as WORD_PROFILE
from ara.docx_analysis_runs import _start
from ara.docx_analysis_worker.control._models import Uncopyable

from . import _registry, database
from ._jobs import Lane
from ._runtime_models import _KEY, _TICKETS, Entry, SupervisorError, SupervisorView, detached
from .sql_models import OwnerBinding

_ISSUED = WeakSet()


class Supervisor(Uncopyable):
    def __new__(cls, key=None, *args):
        if key is not _KEY:
            raise TypeError("supervisors are issued by a factory")
        return super().__new__(cls)

    def __init__(
        self,
        key,
        settings,
        user_id,
        project_id,
        installation_id,
        root,
        execution,
        platform,
        source_profile=PROFILE,
    ):
        self._pid, self._lock, self._wake, self._finished = os.getpid(), RLock(), Event(), Event()
        self._settings, self._user_id, self._project_id = settings, user_id, project_id
        self._installation_id, self._root, self._execution = installation_id, root, execution
        self._source_profile = source_profile
        self._platform, self._owner_binding = platform, OwnerBinding(installation_id, uuid4())
        self._phase, self._error, self._quarantine = "new", None, False
        self._entries, self._order, self._active = {}, 0, None
        self._lanes, self._pending, self._engines = {}, {}, None
        self._thread = None
        self._start_ack = Event()
        self._shutdown = self._start_failed = self._clock_fault = False
        self._coordinator = None
        _ISSUED.add(self)

    def __repr__(self):
        return "<FixtureSupervisor>"

    def _check(self):
        if type(self) is not Supervisor or self not in _ISSUED or self._pid != os.getpid():
            raise SupervisorError("invalid_handle")

    def _threads(self):
        return tuple(lane.thread for lane in self._lanes.values()) + (
            (self._thread,) if self._thread else ()
        )

    def start(self):
        self._check()
        with self._lock:
            if self._phase != "new":
                return self.view()
            _registry.acquire(self)
            self._phase = "starting"
            try:
                self._engines = database.create_engines(self._settings)
                self._lanes = {
                    name: Lane(name, self._wake)
                    for name in (
                        "admission",
                        "control",
                        "publication",
                        "lifecycle",
                        "platform_control",
                    )
                }
                for lane in self._lanes.values():
                    lane.start()
                from ._coordinator import Coordinator

                self._coordinator = Coordinator(self)
                self._thread = Thread(
                    target=self._coordinator.run, name="aira-supervisor-coordinator", daemon=True
                )
                self._thread.start()
                self._start_ack.set()
            except BaseException:
                self._start_failed = True
                self._phase, self._error, self._quarantine = "blocked", "runtime_unavailable", True
        return self.view()

    def view(self):
        self._check()
        with self._lock:
            queued = sum(e is not self._active for e in self._entries.values())
            return SupervisorView(
                self._phase,
                True,
                self._error,
                queued,
                self._active.run_id if self._active else None,
                tuple(self._pending),
                self._quarantine,
            )

    def _ticket(self, ticket):
        if ticket not in _TICKETS or getattr(ticket, "_pid", None) != self._pid:
            raise SupervisorError("invalid_handle")
        if getattr(ticket, "_supervisor", None) is not self:
            raise SupervisorError("invalid_handle")
        return ticket._entry

    def ticket_view(self, ticket):
        self._check()
        with self._lock:
            e = self._ticket(ticket)
            snap = e.snapshot
            if snap is None:
                return e.view()
            return replace(
                snap,
                stop_requested=bool(snap.stop_requested or e.intent),
                sql_state=detached(snap.sql_state),
            )

    def _admit(self, key, command, provider, cls):
        self._check()
        # An already registered intent needs neither a new clock sample nor ready state.
        # Its durable/unknown outcome belongs to the original anchor and ticket.
        if type(command) is cls and type(key) is UUID and type(command.document_id) is UUID:
            with self._lock:
                previous = self._entries.get((command.document_id, key))
            if previous is not None:
                from ara.docx_analysis.storage_codec import encode_command
                from ara.docx_analysis_runs import _storage

                try:
                    encoded = encode_command(command)
                except Exception as error:
                    _start.preparation_error(error)
                if previous.encoded != encoded:
                    _storage.fail("idempotency_conflict", 409)
                return previous.ticket
        try:
            anchor = self._platform.clock()
            if type(anchor) is not int or not 0 <= anchor <= 2**63 - 1 - 300_000_000_000:
                raise ValueError()
        except Exception:
            self._clock_fault = True
            self._wake.set()
            raise SupervisorError("clock_error") from None
        with self._lock:
            if self._phase != "ready" or self._shutdown:
                raise SupervisorError("not_ready")
        from ara.documents.runtime import DocumentRuntime

        runtime = DocumentRuntime(
            engine=self._engines.admission,
            user_id=self._user_id,
            project_id=self._project_id,
            mode="local",
        )
        _, encoded = _start.inputs(runtime, key, command, cls, None, 16)
        with self._lock:
            old = self._entries.get((command.document_id, key))
            if old is not None:
                if old.encoded != encoded:
                    from ara.docx_analysis_runs import _storage

                    _storage.fail("idempotency_conflict", 409)
                return old.ticket
            if sum(e is not self._active for e in self._entries.values()) >= 16:
                raise SupervisorError("queue_full")
            if any(e.phase == "admitting" for e in self._entries.values()):
                raise SupervisorError("busy")
            self._order += 1
            e = Entry(
                key, command, encoded, provider, anchor, anchor + 299_950_000_000, self._order
            )
            e.ticket._supervisor, e.ticket._entry = self, e
            e.snapshot = e.view()
            self._entries[(command.document_id, key)] = e
            self._wake.set()
            return e.ticket

    def admit_saved(self, *, client_request_id, command, target_provider):
        return self._admit(client_request_id, command, target_provider, SavedCheckCommand)

    def retry(self, *, client_request_id, command):
        return self._admit(client_request_id, command, None, RetryCheckCommand)

    def stop(self, ticket):
        self._check()
        with self._lock:
            e = self._ticket(ticket)
            if e.phase not in ("finished", "not_admitted") and e.intent is None:
                e.intent = "user"
            d = e.dispatcher
        if d is not None:
            d.request_stop("user")
        self._wake.set()
        return self.ticket_view(ticket)

    def shutdown(self, *, timeout=5.0):
        self._check()
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 5:
            raise SupervisorError("validation_error")
        end = time.monotonic() + timeout
        with self._lock:
            self._shutdown = True
            if self._phase == "new":
                self._phase = "closed"
                return True
            entries = tuple(self._entries.values())
            for e in entries:
                if e.intent is None:
                    e.intent = "shutdown"
        for e in entries:
            if e.dispatcher is not None:
                e.dispatcher.request_stop("shutdown")
        self._wake.set()
        if current_thread() in self._threads():
            return False
        if self._start_failed:
            for lane in self._lanes.values():
                lane.close()
            return False
        self._finished.wait(max(0, end - time.monotonic()))
        if not self._finished.is_set():
            return False
        for thread in self._threads():
            thread.join(max(0, end - time.monotonic()))
        if any(t.is_alive() for t in self._threads()):
            return False
        _registry.release(self)
        return True


def _create_supervisor(
    *,
    settings,
    user_id,
    project_id,
    installation_id,
    root,
    execution,
    platform,
    source_profile=PROFILE,
):
    from ara.desktop.database import DatabaseError, DesktopDatabaseSettings

    if (
        type(settings) not in (DatabaseSettings, DesktopDatabaseSettings)
        or any(type(v) is not UUID for v in (user_id, project_id, installation_id))
        or not isinstance(root, Path)
        or not root.is_absolute()
        or ".." in root.parts
        or type(execution) is not ExecutionSpec
        or execution.execution_kind != "fixture"
        or type(source_profile) is not str
        or source_profile
        not in (PROFILE, LIST_PROFILE, OUTLINE_PROFILE, STYLE_LIST_PROFILE, WORD_PROFILE)
    ):
        raise SupervisorError("validation_error")
    if type(settings) is DesktopDatabaseSettings:
        try:
            settings.validate_scope(
                user_id=user_id, project_id=project_id, installation_id=installation_id, root=root
            )
        except DatabaseError:
            raise SupervisorError("validation_error") from None
    encode_execution(execution)
    return Supervisor(
        _KEY,
        replace(settings),
        user_id,
        project_id,
        installation_id,
        Path(root),
        replace(execution),
        platform,
        source_profile,
    )


def create_fixture_supervisor(*, settings, user_id, project_id, installation_id, root, execution):
    if sys.platform == "darwin":
        from ._macos_adapter import MacPlatform

        port = MacPlatform()
    elif sys.platform == "win32":
        from ._windows_adapter import WindowsPlatform

        port = WindowsPlatform()
    else:
        raise SupervisorError("runtime_unavailable")
    return _create_supervisor(
        settings=settings,
        user_id=user_id,
        project_id=project_id,
        installation_id=installation_id,
        root=root,
        execution=execution,
        platform=port,
    )
