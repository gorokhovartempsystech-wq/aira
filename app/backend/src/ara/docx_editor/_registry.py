"""Explicit scoped actors with bounded admission and no durable edits on open."""

from copy import copy, deepcopy
from dataclasses import dataclass, field, fields, replace
from threading import Lock, Semaphore
from uuid import UUID, uuid4

from ara.docx_documents._dto import MAX_REVISION, valid_integer
from ara.docx_documents.checkpoints import get_checkpoint
from ara.docx_package.editor import EditorSession

from . import _models
from ._budget import PackageBudget
from ._commands import execute, fingerprint, normalized
from ._errors import editor_boundary, error, safe, validate
from ._recovery import read_source
from ._scope import observe


@dataclass(frozen=True, slots=True, repr=False)
class _ActorState:
    editor: EditorSession = field(repr=False)
    base_revision: int
    base_sha256: str
    checkpoint_revision: int
    checkpoint_phase: str
    handle: object = field(repr=False)
    command_sequence: int = 0
    last_command: object = field(default=None, repr=False)
    active: object = field(default=None, repr=False)
    saved: object = field(default=None, repr=False)


@dataclass(slots=True, repr=False)
class _Actor:
    document_id: UUID
    session_id: UUID
    state: _ActorState = field(repr=False)
    request: tuple
    mutex: object = field(default_factory=Lock, repr=False)


class EditorRegistry:
    def __init__(self, runtime, *, limits=None, table_editor=False):
        from sqlalchemy import Engine

        from ara.documents.runtime import DocumentRuntime

        validate(
            type(runtime) is DocumentRuntime
            and isinstance(getattr(runtime, "engine", None), Engine)
            and type(getattr(runtime, "user_id", None)) is UUID
            and type(getattr(runtime, "project_id", None)) is UUID
            and type(getattr(runtime, "mode", None)) is str
            and runtime.mode == "local"
        )
        validate(type(table_editor) is bool)
        self._editor_type = EditorSession
        if table_editor:
            from ara.docx_package.table_editor import TableEditorSession

            self._editor_type = TableEditorSession
        self._runtime = DocumentRuntime(
            engine=runtime.engine,
            user_id=runtime.user_id,
            project_id=runtime.project_id,
            mode=runtime.mode,
        )
        try:
            if limits is None:
                limits = _models.RegistryLimits()
            if type(limits) is not _models.RegistryLimits:
                raise ValueError("Invalid limits")
            self._limits = _models.RegistryLimits(
                **{f.name: getattr(limits, f.name, None) for f in fields(limits)}
            )
        except (ValueError, TypeError, AttributeError):
            error("validation_error", 422)
        self._registry_id = uuid4()
        self._open_sequence = 0
        self._index = Lock()
        self._opening = Lock()
        self._heavy = Semaphore(1)
        self._actors, self._opens = {}, {}
        self._budget = PackageBudget(self._limits.max_retained_bytes)

    @safe
    def inspect_recovery(self, *, document_id):
        validate(type(document_id) is UUID)
        with self._heavy, read_source(self._runtime, document_id) as source:
            with editor_boundary():
                c = source.checkpoint
                nonempty = c is not None and c.phase != "empty"
                with self._index:
                    sequence = self._open_sequence
                result = _models.RecoveryView(
                    self._registry_id,
                    sequence,
                    source.observation().document,
                    c.checkpoint_revision if c else 0,
                    c.phase if c else "absent",
                    c.base_storage_revision if nonempty else None,
                    c.base_sha256 if nonempty else None,
                    c.working_sha256 if nonempty else None,
                    len(c.working_data) if nonempty else None,
                    deepcopy(c.metadata.selection) if nonempty else None,
                    deepcopy(c.metadata.origin) if nonempty else None,
                    source.status.state if source.status else None,
                    source.handle.operation_id if source.handle else None,
                )
        return result

    def _view(
        self,
        actor,
        observation,
        status=None,
        handle=None,
        *,
        state=None,
        active_matches=None,
        active_head_matches=None,
        active_save_state=None,
    ):
        with editor_boundary():
            state = actor.state if state is None else state
            mode = "editable"
            head_matches = (state.base_revision, state.base_sha256) == (
                observation.document.storage_revision,
                observation.document.current_sha256,
            )
            fence_matches = (state.checkpoint_revision, state.checkpoint_phase) == (
                observation.revision,
                observation.phase,
            )
            if state.handle is not None:
                same_pending = handle == state.handle and fence_matches
                mode = (
                    "recovery_pending"
                    if same_pending
                    and status is not None
                    and status.state in ("ready", "committed", "exhausted")
                    else "conflict"
                )
            elif not head_matches or not fence_matches:
                mode = "conflict"
            if state.active is not None:
                unchanged = (state.checkpoint_revision, state.checkpoint_phase) == (
                    observation.revision,
                    observation.phase,
                )
                maybe_ack = (
                    observation.revision == state.checkpoint_revision + 1
                    and observation.phase == "working"
                )
                mode = (
                    "operation_pending"
                    if (head_matches if active_head_matches is None else active_head_matches)
                    and active_matches is not False
                    and (active_matches is True or unchanged or maybe_ack)
                    else "conflict"
                )
            return _models.EditorView(
                self._registry_id,
                actor.document_id,
                actor.session_id,
                state.command_sequence,
                state.editor.snapshot(),
                state.base_revision,
                state.base_sha256,
                state.checkpoint_revision,
                observation.document,
                observation.revision,
                observation.phase,
                mode,
                state.handle.operation_id if state.handle else None,
                deepcopy(state.last_command),
                (
                    state.active.descriptor(active_save_state)
                    if hasattr(state.active, "handle")
                    else state.active.descriptor()
                )
                if state.active is not None
                else None,
            )

    def _ensure_live(self, actor):
        with self._index:
            present = self._actors.get((actor.document_id, actor.session_id)) is actor
        if not present:
            error("editor_session_expired", 410)

    def _live_view(self, actor):
        if actor.state.active is not None:
            if hasattr(actor.state.active, "handle"):
                from ._save import live_view

                return live_view(self, actor)
            from ._controls import live_view

            return live_view(self, actor)
        if actor.state.handle is not None:
            with read_source(self._runtime, actor.document_id, handle=actor.state.handle) as source:
                self._ensure_live(actor)
                result = self._view(actor, source.observation(), source.status, source.handle)
        else:
            with observe(self._runtime, actor.document_id) as observation:
                self._ensure_live(actor)
                result = self._view(actor, observation)
        return result

    @safe
    def snapshot(self, *, document_id, session_id):
        validate(type(document_id) is UUID and type(session_id) is UUID)
        with self._index:
            actor = self._actors.get((document_id, session_id))
        if actor is None:
            with observe(self._runtime, document_id):
                error("editor_session_expired", 410)
        with actor.mutex, self._heavy:
            return self._live_view(actor)

    @safe
    def working_target(
        self,
        *,
        document_id,
        session_id,
        expected_command_sequence,
        expected_session_revision,
        expected_sha256,
    ):
        from ._downloads import working

        return working(
            self,
            document_id,
            session_id,
            expected_command_sequence,
            expected_session_revision,
            expected_sha256,
        )

    @safe
    def recovery_target(self, *, document_id, expected_checkpoint_revision, expected_sha256):
        from ._downloads import recovery

        return recovery(self, document_id, expected_checkpoint_revision, expected_sha256)

    @safe
    def saved_target(
        self,
        *,
        document_id,
        session_id,
        command_id,
        expected_command_sequence,
        expected_session_revision,
    ):
        validate(
            all(type(v) is UUID for v in (document_id, session_id, command_id))
            and valid_integer(expected_command_sequence, 0, MAX_REVISION)
            and valid_integer(expected_session_revision, 0, MAX_REVISION)
        )
        with self._index:
            actor = self._actors.get((document_id, session_id))
        if actor is None:
            with observe(self._runtime, document_id):
                error("editor_session_expired", 410)
        with actor.mutex, self._heavy:
            with observe(self._runtime, document_id):
                self._ensure_live(actor)
                state = actor.state
                if state.active is not None:
                    error("editor_operation_pending")
                target = state.saved
                if target is None or (
                    target.command_id,
                    target.command_sequence,
                    target.session_revision,
                ) != (command_id, expected_command_sequence, expected_session_revision):
                    error("stale_command")
                with editor_boundary():
                    result = deepcopy(target)
                    result.__post_init__()
            return result

    @safe
    def command(
        self,
        *,
        document_id,
        session_id,
        command_id,
        expected_command_sequence,
        expected_session_revision,
        command,
    ):
        validate(
            all(type(v) is UUID for v in (document_id, session_id, command_id))
            and valid_integer(expected_command_sequence, 0, MAX_REVISION)
            and valid_integer(expected_session_revision, 0, MAX_REVISION)
        )
        command = normalized(command)
        digest = fingerprint(
            self._registry_id,
            document_id,
            session_id,
            command_id,
            expected_command_sequence,
            expected_session_revision,
            command,
        )
        with self._index:
            actor = self._actors.get((document_id, session_id))
        if actor is None:
            with observe(self._runtime, document_id):
                error("editor_session_expired", 410)
        with actor.mutex, self._heavy:
            state = actor.state
            if (
                state.active is not None
                and state.last_command is not None
                and state.last_command.command_id == command_id
            ):
                with observe(self._runtime, document_id):
                    self._ensure_live(actor)
                    last = state.last_command
                    if (
                        last.request_sha256,
                        last.expected_command_sequence,
                        last.expected_session_revision,
                    ) != (digest, expected_command_sequence, expected_session_revision):
                        error("idempotency_conflict")
                # Full active proof, without retaining the outer connection's
                # read locks. The accepted edit is not executed again.
                return self._live_view(actor)
            reservation = uuid4()
            try:
                with observe(self._runtime, document_id) as observation:
                    self._ensure_live(actor)
                    state = actor.state
                    last = state.last_command
                    if last is not None and last.command_id == command_id:
                        if (
                            last.request_sha256,
                            last.expected_command_sequence,
                            last.expected_session_revision,
                        ) != (digest, expected_command_sequence, expected_session_revision):
                            error("idempotency_conflict")
                        return self._view(actor, observation)
                    before = state.editor.snapshot()
                    if (expected_command_sequence, expected_session_revision) != (
                        state.command_sequence,
                        before.document.revision,
                    ):
                        error("stale_command")
                    if state.handle is not None or state.active is not None:
                        error("editor_operation_pending")
                    if (state.base_revision, state.base_sha256) != (
                        observation.document.storage_revision,
                        observation.document.current_sha256,
                    ):
                        error("docx_conflict")
                    if (state.checkpoint_revision, state.checkpoint_phase) != (
                        observation.revision,
                        observation.phase,
                    ):
                        error("checkpoint_conflict")
                    if state.command_sequence == MAX_REVISION or (
                        command.action != "capture" and before.document.revision == MAX_REVISION
                    ):
                        error("revision_exhausted")
                    with editor_boundary():
                        candidate = copy(state.editor)
                        # Expected native failures are mapped before the SQL boundary catches them.
                        result = execute(candidate, command, expected_session_revision)
                        receipt = _models.CommandReceipt(
                            command_id,
                            digest,
                            command.action,
                            expected_command_sequence,
                            expected_session_revision,
                            expected_command_sequence + 1,
                            result.document.revision,
                            result.position_id,
                        )
                        future = replace(
                            state,
                            editor=candidate,
                            command_sequence=state.command_sequence + 1,
                            last_command=receipt,
                            saved=None,
                        )
                        reply = self._view(actor, observation, state=future)
                        packages = candidate._retained_packages()
                        with self._index:
                            self._budget.reserve(reservation, packages)
                with self._index:
                    self._budget.groups[actor.session_id] = packages
                    actor.state = future
                    self._budget.release(reservation)
                return reply
            finally:
                with self._index:
                    self._budget.release(reservation)

    def _control(
        self,
        action,
        document_id,
        session_id,
        command_id,
        expected_command_sequence,
        expected_session_revision,
        mode=None,
    ):
        validate(
            all(type(v) is UUID for v in (document_id, session_id, command_id))
            and valid_integer(expected_command_sequence, 0, MAX_REVISION)
            and valid_integer(expected_session_revision, 0, MAX_REVISION)
        )
        if action == "close":
            validate(type(mode) is str and mode in ("checkpoint", "release_local"))
        from ._controls import run

        return run(
            self,
            action=action,
            document_id=document_id,
            session_id=session_id,
            command_id=command_id,
            expected_command_sequence=expected_command_sequence,
            expected_session_revision=expected_session_revision,
            mode=mode,
        )

    @safe
    def checkpoint(
        self,
        *,
        document_id,
        session_id,
        command_id,
        expected_command_sequence,
        expected_session_revision,
    ):
        return self._control(
            "checkpoint",
            document_id,
            session_id,
            command_id,
            expected_command_sequence,
            expected_session_revision,
        )

    @safe
    def save(
        self,
        *,
        document_id,
        session_id,
        command_id,
        expected_command_sequence,
        expected_session_revision,
    ):
        return self._control(
            "save",
            document_id,
            session_id,
            command_id,
            expected_command_sequence,
            expected_session_revision,
        )

    @safe
    def reconcile(
        self,
        *,
        document_id,
        session_id,
        command_id,
        expected_command_sequence,
        expected_session_revision,
    ):
        return self._control(
            "reconcile",
            document_id,
            session_id,
            command_id,
            expected_command_sequence,
            expected_session_revision,
        )

    @safe
    def close(
        self,
        *,
        document_id,
        session_id,
        command_id,
        expected_command_sequence,
        expected_session_revision,
        mode="checkpoint",
    ):
        return self._control(
            "close",
            document_id,
            session_id,
            command_id,
            expected_command_sequence,
            expected_session_revision,
            mode,
        )

    @safe
    def open(
        self,
        *,
        document_id,
        registry_id,
        client_open_id,
        expected_open_sequence,
        expected_checkpoint_revision,
        mode,
    ):
        validate(
            all(type(v) is UUID for v in (document_id, registry_id, client_open_id))
            and valid_integer(expected_open_sequence, 0, MAX_REVISION)
            and valid_integer(expected_checkpoint_revision, 0, MAX_REVISION)
            and type(mode) is str
            and mode in ("current", "recover")
        )
        request = (
            document_id,
            registry_id,
            client_open_id,
            expected_open_sequence,
            expected_checkpoint_revision,
            mode,
        )
        with self._opening:
            with observe(self._runtime, document_id):
                if registry_id != self._registry_id:
                    error("editor_registry_expired", 410)
                with self._index:
                    actor = self._opens.get(client_open_id)
                if actor is not None and actor.request != request:
                    error("idempotency_conflict")
            if actor is not None:
                with actor.mutex, self._heavy:
                    view = self._live_view(actor)
                    with self._index:
                        sequence = self._open_sequence
                    return _models.OpenedEditor(view, expected_open_sequence, sequence)
            with self._index:
                if expected_open_sequence != self._open_sequence:
                    error("stale_open")
                if self._open_sequence == MAX_REVISION:
                    error("revision_exhausted")
                if len(self._actors) >= self._limits.max_sessions:
                    error("editor_limit_exceeded", 413)
            with self._heavy:
                # Initialization owns its transaction; no outer document lock.
                if expected_checkpoint_revision == 0 and mode == "current":
                    initialized = get_checkpoint(self._runtime, document_id=document_id).checkpoint
                    if not (
                        initialized.phase == "empty"
                        and initialized.checkpoint_revision == 1
                        and initialized.last_request_id is None
                        and initialized.last_request_sha256 is None
                    ):
                        error("checkpoint_conflict")
                token, admitted = uuid4(), False
                try:
                    with read_source(self._runtime, document_id) as source:
                        c = source.checkpoint
                        revision = c.checkpoint_revision if c else 0
                        expected = (
                            1
                            if expected_checkpoint_revision == 0 and mode == "current"
                            else expected_checkpoint_revision
                        )
                        if (
                            revision != expected
                            or c is None
                            or ((mode == "current") != (c.phase == "empty"))
                        ):
                            error("checkpoint_conflict")
                        with editor_boundary():
                            if mode == "current":
                                editor = self._editor_type(source.document.current_data)
                                base, digest = (
                                    source.document.storage_revision,
                                    source.document.current_sha256,
                                )
                            else:
                                editor = self._editor_type.restore(
                                    c.working_data,
                                    saved_sha256=c.base_sha256,
                                    selection=c.metadata.selection,
                                )
                                base, digest = c.base_storage_revision, c.base_sha256
                            actor = _Actor(
                                document_id,
                                token,
                                _ActorState(
                                    editor, base, digest, revision, c.phase, deepcopy(source.handle)
                                ),
                                request,
                            )
                            view = self._view(
                                actor, source.observation(), source.status, source.handle
                            )
                            reply = _models.OpenedEditor(
                                view, expected_open_sequence, expected_open_sequence + 1
                            )
                            with self._index:
                                self._budget.reserve(token, editor._retained_packages())
                    # All read commits succeeded; candidate/reply/admission are ready.
                    with self._index:
                        self._actors[(document_id, token)] = actor
                        self._opens[client_open_id] = actor
                        self._open_sequence += 1
                        admitted = True
                    return reply
                finally:
                    if not admitted:
                        with self._index:
                            self._budget.release(token)
