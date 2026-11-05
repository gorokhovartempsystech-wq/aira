"""Strict detached runtime records; payloads stay out of diagnostics."""

from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID

from ara.docx_documents._dto import MAX_REVISION, DocxSummary, _hash, valid_integer
from ara.docx_package.checkpoint import CheckpointOrigin
from ara.docx_package.editor import EditorSelection, EditorSnapshot
from ara.docx_package.projection import DocxProjection

from ._commands import ACTIONS

CONTROL_ACTIONS = ("checkpoint", "save")


def _require(condition):
    if not condition:
        raise ValueError("Invalid DOCX editor record")


def _counter(value, lower=0):
    return valid_integer(value, lower, MAX_REVISION)


def _summary(value):
    _require(type(value) is DocxSummary)
    value.__post_init__()


@dataclass(frozen=True, slots=True)
class RegistryLimits:
    max_sessions: int = 8
    max_retained_bytes: int = 268435456

    def __post_init__(self):
        _require(
            all(type(v) is int and v > 0 for v in (self.max_sessions, self.max_retained_bytes))
        )


@dataclass(frozen=True, slots=True)
class RecoveryView:
    registry_id: UUID
    open_sequence: int
    document: DocxSummary = field(repr=False)
    checkpoint_revision: int
    phase: str
    base_storage_revision: int | None
    base_sha256: str | None
    working_sha256: str | None
    working_size_bytes: int | None
    selection: EditorSelection | None = field(repr=False)
    origin: CheckpointOrigin | None = field(repr=False)
    pending_status: str | None
    operation_id: UUID | None

    def __post_init__(self):
        _require(
            type(self.registry_id) is UUID
            and _counter(self.open_sequence)
            and _counter(self.checkpoint_revision)
            and type(self.phase) is str
            and self.phase in ("absent", "empty", "working", "pending")
            and (self.phase == "absent") == (self.checkpoint_revision == 0)
        )
        _summary(self.document)
        if self.phase in ("absent", "empty"):
            _require(
                all(
                    v is None
                    for v in (
                        self.base_storage_revision,
                        self.base_sha256,
                        self.working_sha256,
                        self.working_size_bytes,
                        self.selection,
                        self.origin,
                        self.pending_status,
                        self.operation_id,
                    )
                )
            )
        else:
            _require(
                _counter(self.base_storage_revision, 1)
                and _hash(self.base_sha256)
                and _hash(self.working_sha256)
                and valid_integer(self.working_size_bytes, 1, 33554432)
                and type(self.selection) is EditorSelection
                and type(self.origin) is CheckpointOrigin
            )
            self.selection.__post_init__()
            self.origin.__post_init__()
            _require(
                all(
                    p.anchor.source_sha256 == self.working_sha256
                    for p in (self.selection.anchor, self.selection.focus)
                )
            )
            if self.phase == "pending":
                _require(
                    type(self.operation_id) is UUID
                    and type(self.pending_status) is str
                    and self.pending_status
                    in ("ready", "conflict", "exhausted", "committed", "committed_outdated")
                )
            else:
                _require(self.operation_id is None and self.pending_status is None)


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    command_id: UUID
    request_sha256: str
    action: str
    expected_command_sequence: int
    expected_session_revision: int
    result_command_sequence: int
    result_session_revision: int
    result_position_id: int

    def __post_init__(self):
        _require(
            type(self.command_id) is UUID
            and _hash(self.request_sha256)
            and type(self.action) is str
            and self.action in (*ACTIONS, *CONTROL_ACTIONS)
            and _counter(self.expected_command_sequence)
            and _counter(self.expected_session_revision)
            and _counter(self.result_command_sequence, 1)
            and self.result_command_sequence == self.expected_command_sequence + 1
            and _counter(self.result_session_revision)
            and self.result_session_revision
            in (self.expected_session_revision, self.expected_session_revision + 1)
            and _counter(self.result_position_id)
            and self.result_position_id <= self.result_session_revision
        )


@dataclass(frozen=True, slots=True)
class EditorView:
    registry_id: UUID
    document_id: UUID
    session_id: UUID
    command_sequence: int
    editor: EditorSnapshot = field(repr=False)
    base_storage_revision: int
    base_sha256: str
    checkpoint_revision: int
    observed_current: DocxSummary = field(repr=False)
    observed_checkpoint_revision: int
    observed_checkpoint_phase: str
    state: str
    recovery_operation_id: UUID | None
    last_command: CommandReceipt | None = field(default=None, repr=False)
    active_command: "ActiveCommand | None" = field(default=None, repr=False)

    def __post_init__(self):
        _require(
            all(type(v) is UUID for v in (self.registry_id, self.document_id, self.session_id))
            and _counter(self.command_sequence)
            and (self.active_command is None or type(self.active_command) is ActiveCommand)
            and _counter(self.base_storage_revision, 1)
            and _hash(self.base_sha256)
            and _counter(self.checkpoint_revision, 1)
            and _counter(self.observed_checkpoint_revision)
            and type(self.observed_checkpoint_phase) is str
            and self.observed_checkpoint_phase in ("absent", "empty", "working", "pending")
            and (self.observed_checkpoint_phase == "absent")
            == (self.observed_checkpoint_revision == 0)
            and type(self.state) is str
            and self.state in ("editable", "recovery_pending", "conflict", "operation_pending")
            and (self.recovery_operation_id is None or type(self.recovery_operation_id) is UUID)
            and type(self.editor) is EditorSnapshot
        )
        self.editor.__post_init__()
        d = self.editor.document
        _require(
            _counter(d.revision)
            and _counter(self.editor.position_id)
            and type(d.data) is bytes
            and 1 <= len(d.data) <= 33554432
            and type(d.is_dirty) is bool
            and _counter(d.undo_depth)
            and _counter(d.redo_depth)
            and d.undo_depth + d.redo_depth + 1 <= 100
            and self.editor.position_id <= d.revision
            and type(d.projection) is DocxProjection
        )
        digest = sha256(d.data).hexdigest()
        _require(
            d.projection.source.sha256 == digest
            and d.is_dirty == (digest != self.base_sha256)
            and all(
                caret.anchor.source_sha256 == digest
                for caret in (self.editor.selection.anchor, self.editor.selection.focus)
            )
        )
        _summary(self.observed_current)
        _require(self.observed_current.document_id == self.document_id)
        if self.active_command is not None:
            self.active_command.__post_init__()
            _require(
                self.active_command.expected_command_sequence == self.command_sequence
                and self.active_command.expected_session_revision == d.revision
                and self.state in ("operation_pending", "conflict")
            )
        if self.last_command is not None:
            _require(type(self.last_command) is CommandReceipt)
            self.last_command.__post_init__()
            _require(
                (
                    self.last_command.result_command_sequence,
                    self.last_command.result_session_revision,
                    self.last_command.result_position_id,
                )
                == (self.command_sequence, d.revision, self.editor.position_id)
            )
        if self.state == "editable":
            _require(
                self.recovery_operation_id is None
                and self.checkpoint_revision == self.observed_checkpoint_revision
                and (self.base_storage_revision, self.base_sha256)
                == (self.observed_current.storage_revision, self.observed_current.current_sha256)
            )
        if self.state == "recovery_pending":
            _require(self.recovery_operation_id is not None)
        if self.state == "operation_pending":
            _require(self.active_command is not None)


@dataclass(frozen=True, slots=True)
class ActiveCommand:
    command_id: UUID
    action: str
    request_sha256: str
    expected_command_sequence: int
    expected_session_revision: int
    stage: str
    operation_id: UUID | None = None
    save_state: str | None = None

    def __post_init__(self):
        _require(
            type(self.command_id) is UUID
            and _hash(self.request_sha256)
            and type(self.action) is str
            and self.action in (*CONTROL_ACTIONS, "close")
            and _counter(self.expected_command_sequence)
            and _counter(self.expected_session_revision)
            and type(self.stage) is str
            and self.stage in ("checkpoint_pending", "save_pending")
        )
        if self.stage == "save_pending":
            _require(
                self.action == "save"
                and type(self.operation_id) is UUID
                and (
                    self.save_state is None
                    or (
                        type(self.save_state) is str
                        and self.save_state
                        in (
                            "ready",
                            "conflict",
                            "exhausted",
                            "committed",
                            "committed_outdated",
                            "superseded",
                        )
                    )
                )
            )
        else:
            _require(self.operation_id is None and self.save_state is None)


@dataclass(frozen=True, slots=True)
class SavedTarget:
    registry_id: UUID
    document_id: UUID
    session_id: UUID
    command_id: UUID
    command_sequence: int
    session_revision: int
    storage_revision: int
    sha256: str
    data: bytes = field(repr=False)

    def __post_init__(self):
        _require(
            all(
                type(v) is UUID
                for v in (self.registry_id, self.document_id, self.session_id, self.command_id)
            )
            and _counter(self.command_sequence, 1)
            and _counter(self.session_revision)
            and _counter(self.storage_revision, 1)
            and _hash(self.sha256)
            and type(self.data) is bytes
            and 1 <= len(self.data) <= 33554432
            and sha256(self.data).hexdigest() == self.sha256
        )


@dataclass(frozen=True, slots=True)
class WorkingTarget:
    registry_id: UUID
    document_id: UUID
    session_id: UUID
    command_sequence: int
    session_revision: int
    sha256: str
    data: bytes = field(repr=False)

    def __post_init__(self):
        _require(
            all(type(v) is UUID for v in (self.registry_id, self.document_id, self.session_id))
            and _counter(self.command_sequence)
            and _counter(self.session_revision)
            and _hash(self.sha256)
            and type(self.data) is bytes
            and 1 <= len(self.data) <= 33554432
            and sha256(self.data).hexdigest() == self.sha256
        )


@dataclass(frozen=True, slots=True)
class RecoveryTarget:
    document_id: UUID
    checkpoint_revision: int
    sha256: str
    data: bytes = field(repr=False)

    def __post_init__(self):
        _require(
            type(self.document_id) is UUID
            and _counter(self.checkpoint_revision, 1)
            and _hash(self.sha256)
            and type(self.data) is bytes
            and 1 <= len(self.data) <= 33554432
            and sha256(self.data).hexdigest() == self.sha256
        )


@dataclass(frozen=True, slots=True)
class ClosedEditor:
    registry_id: UUID
    document_id: UUID
    session_id: UUID
    mode: str
    checkpoint_revision: int | None

    def __post_init__(self):
        _require(
            all(type(v) is UUID for v in (self.registry_id, self.document_id, self.session_id))
            and type(self.mode) is str
            and self.mode in ("checkpoint", "release_local")
            and (
                self.checkpoint_revision is None
                if self.mode == "release_local"
                else _counter(self.checkpoint_revision, 1)
            )
        )


@dataclass(frozen=True, slots=True)
class OpenedEditor:
    view: EditorView = field(repr=False)
    accepted_open_sequence: int
    next_open_sequence: int

    def __post_init__(self):
        _require(
            type(self.view) is EditorView
            and valid_integer(self.accepted_open_sequence, 0, MAX_REVISION - 1)
            and _counter(self.next_open_sequence, 1)
            and self.accepted_open_sequence < self.next_open_sequence
        )
        self.view.__post_init__()
