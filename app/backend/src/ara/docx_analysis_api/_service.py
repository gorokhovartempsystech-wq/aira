"""Bounded per-app receipt cache; no SQL, codec or native call under its lock."""

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock

from sqlalchemy.engine import make_url

from ara.config import ConfigurationError
from ara.documents.runtime import DocumentRuntime
from ara.docx_analysis.storage_codec import SavedCheckCommand, encode_command
from ara.docx_analysis_worker.supervisor.runtime import Supervisor
from ara.docx_editor import EditorRegistry

from . import _reads, _wire


@dataclass(eq=False, repr=False)
class Entry:
    digest: str
    ticket: object = None
    stop: bool = False
    phase: str = "admitting"


class Service:
    def __init__(self, runtime, registry, supervisor):
        from ara.desktop.database import DesktopDatabaseSettings
        from ara.desktop.database.http_binding import bind_http_runtime

        desktop_runtime = None
        try:
            if type(supervisor) is not Supervisor or type(registry) is not EditorRegistry:
                raise ValueError()
            supervisor._check()
            if type(runtime) is not DocumentRuntime or runtime.engine.dialect.name != "postgresql":
                raise ValueError()
            if type(supervisor._settings) is DesktopDatabaseSettings:
                desktop_runtime = bind_http_runtime(
                    supervisor._settings,
                    runtime,
                    registry._runtime,
                    user_id=supervisor._user_id,
                    project_id=supervisor._project_id,
                    installation_id=supervisor._installation_id,
                    root=supervisor._root,
                )
            else:
                expected = (runtime.user_id, runtime.project_id, runtime.engine.url)
                if expected != (
                    supervisor._user_id,
                    supervisor._project_id,
                    make_url(supervisor._settings.database_url.get_secret_value()),
                ) or expected != (
                    registry._runtime.user_id,
                    registry._runtime.project_id,
                    registry._runtime.engine.url,
                ):
                    raise ValueError()
        except Exception:
            raise ConfigurationError(
                "Analysis requires matching explicit runtime and supervisor"
            ) from None
        self.runtime = (
            desktop_runtime if desktop_runtime is not None else _reads.read_runtime(runtime)
        )
        self.registry, self.supervisor = registry, supervisor
        self._lock, self._entries = RLock(), OrderedDict()

    def close(self):
        self.runtime.engine.dispose()

    def _refresh(self):
        with self._lock:
            pairs = [
                (key, entry, entry.ticket) for key, entry in self._entries.items() if entry.ticket
            ]
        views = [(key, entry, self.supervisor.ticket_view(ticket)) for key, entry, ticket in pairs]
        with self._lock:
            for key, entry, view in views:
                if self._entries.get(key) is entry:
                    entry.phase = view.phase
            terminal = [
                key for key, e in self._entries.items() if e.phase in ("finished", "not_admitted")
            ]
            for key in terminal[:-128]:
                del self._entries[key]

    def _receipt(self, document_id, key, entry):
        with self._lock:
            ticket, stopped = entry.ticket, entry.stop
            if self._entries.get((document_id, key)) is entry:
                self._entries.move_to_end((document_id, key))
        view = self.supervisor.ticket_view(ticket) if ticket else None
        return _wire.receipt(
            document_id, key, view, stopped=stopped, fixture=self.supervisor.view().fixture
        )

    def admit(self, key, command):
        document_id = command.document_id
        _reads.scope_check(self.runtime, document_id)
        digest = encode_command(command).sha256
        self._refresh()
        identity = document_id, key
        with self._lock:
            entry = self._entries.get(identity)
            if entry is not None:
                if entry.digest != digest:
                    _reads.fail("idempotency_conflict", 409)
                if entry.phase == "not_admitted":
                    del self._entries[identity]
                    entry = None
            create = entry is None
            if create:
                if (
                    sum(e.phase not in ("finished", "not_admitted") for e in self._entries.values())
                    >= 17
                ):
                    _reads.fail("analysis_busy", 503)
                entry = Entry(digest)
                self._entries[identity] = entry
        if create:
            try:
                if type(command) is SavedCheckCommand:

                    def provider():
                        return self.registry.saved_target(
                            document_id=document_id,
                            session_id=command.session_id,
                            command_id=command.save_command_id,
                            expected_command_sequence=command.command_sequence,
                            expected_session_revision=command.session_revision,
                        )

                    ticket = self.supervisor.admit_saved(
                        client_request_id=key,
                        command=command,
                        target_provider=provider,
                    )
                else:
                    ticket = self.supervisor.retry(client_request_id=key, command=command)
            except BaseException:
                with self._lock:
                    if self._entries.get(identity) is entry:
                        del self._entries[identity]
                raise
            with self._lock:
                entry.ticket, stopped = ticket, entry.stop
            if stopped:
                self.supervisor.stop(ticket)
        return self._receipt(document_id, key, entry)

    def receipt(self, document_id, key):
        _reads.scope_check(self.runtime, document_id)
        self._refresh()
        with self._lock:
            entry = self._entries.get((document_id, key))
        if entry is not None:
            return self._receipt(document_id, key, entry)
        return _wire.durable_receipt(*_reads.get_request(self.runtime, document_id, key))

    def stop(self, document_id, key):
        with self._lock:
            entry = self._entries.get((document_id, key))
            if entry is not None:
                ticket = entry.ticket
                # Do not invent Stop for already terminal metadata.
                if ticket is None:
                    entry.stop = True
        if entry is None:
            summary, code = _reads.get_request(self.runtime, document_id, key)
            if summary.status not in ("succeeded", "failed", "cancelled", "timed_out"):
                _reads.fail("recovery_required", 409)
            return _wire.durable_receipt(summary, code)
        if ticket is not None:
            self.supervisor.stop(ticket)
        return self._receipt(document_id, key, entry)
