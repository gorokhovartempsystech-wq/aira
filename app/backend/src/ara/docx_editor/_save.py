"""Stable dirty-save identity and read-only proof across independent transactions."""

from copy import copy, deepcopy
from dataclasses import dataclass, field, replace
from uuid import uuid4

from ara.docx_documents._dto import MAX_REVISION
from ara.docx_documents.checkpoint_fingerprints import pending_fingerprint
from ara.docx_documents.checkpoint_models import CheckpointSnapshot
from ara.docx_documents.checkpoints import _legacy, _record
from ara.docx_documents.save_commit import _committed, _matches, commit_save
from ara.docx_documents.save_finalize import _control_fingerprint, finalize_save
from ara.docx_documents.save_models import FinalizedSave, SaveHandle
from ara.docx_documents.save_prepare import prepare_save
from ara.docx_package.checkpoint import (
    CheckpointMetadata,
    CheckpointOrigin,
    decode_metadata,
    encode_metadata,
)

from . import _models
from ._controls import SaveTarget, _binding, _target
from ._errors import editor_boundary, error, native_errors
from ._scope import Observation, summary


@dataclass(frozen=True, slots=True, repr=False)
class SaveAttempt:
    action: str
    command_id: object
    request_sha256: str
    expected_command_sequence: int
    expected_session_revision: int
    target: SaveTarget = field(repr=False)
    data: bytes = field(repr=False)
    metadata: object = field(repr=False)
    prepare_request_id: object
    finalize_request_id: object
    expected_checkpoint_revision: int
    handle: SaveHandle = field(repr=False)
    marked: object = field(repr=False)
    recovered: bool

    def descriptor(self, save_state=None):
        return _models.ActiveCommand(
            self.command_id,
            "save",
            self.request_sha256,
            self.expected_command_sequence,
            self.expected_session_revision,
            "save_pending",
            self.handle.operation_id,
            save_state,
        )


def build(registry, actor, state, snapshot, command_id, digest, *, recovered=False):
    target = _target(registry, actor, state, snapshot)
    marked = copy(state.editor)
    with native_errors():
        marked.mark_saved(expected_revision=target.revision)
        if recovered:
            handle = deepcopy(state.handle)
            handle.__post_init__()
            if (
                handle.document_id != actor.document_id
                or handle.working_sha256 != target.sha256
                or handle.working_size_bytes != target.size_bytes
                or handle.metadata.selection != target.selection
            ):
                error("editor_error", 500)
            metadata = CheckpointMetadata(
                deepcopy(handle.metadata.selection), deepcopy(handle.metadata.origin)
            )
            expected = handle.prepared_checkpoint_revision - 1
        else:
            if state.checkpoint_revision >= MAX_REVISION - 1 or state.base_revision == MAX_REVISION:
                error("revision_exhausted")
            expected = state.checkpoint_revision
            metadata = CheckpointMetadata(
                deepcopy(snapshot.selection),
                CheckpointOrigin(actor.session_id, target.revision, target.position_id),
            )
            operation = uuid4()
            wire = encode_metadata(
                metadata,
                data=snapshot.document.data,
                saved_sha256=state.base_sha256,
                phase="working",
            )
            wire["pending"] = {"operation_id": str(operation), "request_sha256": "0" * 64}
            wire["pending"]["request_sha256"] = pending_fingerprint(
                actor.document_id,
                expected + 1,
                state.base_revision,
                state.base_sha256,
                snapshot.document.data,
                wire,
            )
            pending = decode_metadata(
                wire, data=snapshot.document.data, saved_sha256=state.base_sha256, phase="pending"
            )
            handle = SaveHandle(
                actor.document_id,
                expected + 1,
                state.base_revision,
                state.base_sha256,
                target.sha256,
                target.size_bytes,
                pending,
            )
    # The marked fork shares compressed packages with the live editor. Verify
    # union admission before any durable dispatch, without retaining a projection.
    token = uuid4()
    with registry._index:
        try:
            registry._budget.reserve(token, marked._retained_packages())
        finally:
            registry._budget.release(token)
    return SaveAttempt(
        "save",
        command_id,
        digest,
        state.command_sequence,
        target.revision,
        target,
        snapshot.document.data,
        metadata,
        uuid4(),
        uuid4(),
        expected,
        handle,
        marked,
        recovered,
    )


def _prepare(registry, actor, attempt):
    result = prepare_save(
        registry._runtime,
        document_id=actor.document_id,
        expected_checkpoint_revision=attempt.expected_checkpoint_revision,
        request_id=attempt.prepare_request_id,
        operation_id=attempt.handle.operation_id,
        base_storage_revision=attempt.handle.base_storage_revision,
        base_sha256=attempt.handle.base_sha256,
        data=attempt.data,
        metadata=attempt.metadata,
    )
    with editor_boundary():
        result.__post_init__()
        if (
            result.handle != attempt.handle
            or result.snapshot.checkpoint.working_data != attempt.data
        ):
            error("editor_error", 500)


def make_target(registry, actor, attempt, storage_revision):
    return _models.SavedTarget(
        registry._registry_id,
        actor.document_id,
        actor.session_id,
        attempt.command_id,
        attempt.expected_command_sequence + 1,
        attempt.target.revision,
        storage_revision,
        attempt.target.sha256,
        attempt.data,
    )


def perform(registry, actor, *, fresh=False):
    from ara.documents.storage import DocumentError

    attempt = actor.state.active
    if not _binding(registry, actor, actor.state, attempt):
        error("editor_error", 500)
    if fresh:
        _prepare(registry, actor, attempt)
        committed = commit_save(registry._runtime, handle=attempt.handle)
    else:
        try:
            committed = commit_save(registry._runtime, handle=attempt.handle)
        except DocumentError as exc:
            if attempt.recovered or exc.code != "checkpoint_conflict":
                raise
            _prepare(registry, actor, attempt)
            committed = commit_save(registry._runtime, handle=attempt.handle)
    if not committed.current_matches_receipt:
        error("docx_conflict")
    final = finalize_save(
        registry._runtime, handle=attempt.handle, request_id=attempt.finalize_request_id
    )
    with editor_boundary():
        final.__post_init__()
        if not final.current_matches_receipt:
            error("docx_conflict")
        if final.handle != attempt.handle or final.snapshot.checkpoint.working_data != attempt.data:
            error("editor_error", 500)
        if not _binding(registry, actor, actor.state, attempt):
            error("editor_error", 500)
        state = actor.state
        target = make_target(registry, actor, attempt, final.receipt.storage_revision)
        receipt = _models.CommandReceipt(
            attempt.command_id,
            attempt.request_sha256,
            "save",
            attempt.expected_command_sequence,
            attempt.expected_session_revision,
            state.command_sequence + 1,
            attempt.target.revision,
            attempt.target.position_id,
        )
        future = replace(
            state,
            editor=attempt.marked,
            base_revision=final.receipt.storage_revision,
            base_sha256=attempt.handle.working_sha256,
            checkpoint_revision=final.snapshot.checkpoint.checkpoint_revision,
            checkpoint_phase="working",
            handle=None,
            command_sequence=state.command_sequence + 1,
            last_command=receipt,
            active=None,
            saved=target,
        )
        reply = registry._view(
            actor,
            Observation(
                summary(final.snapshot.document),
                final.snapshot.checkpoint.checkpoint_revision,
                "working",
            ),
            state=future,
        )
        with registry._index:
            actor.state = future
            registry._budget.groups[actor.session_id] = future.editor._retained_packages()
        return reply


def live_view(registry, actor):
    from sqlalchemy import select

    from ara.documents.storage import _session
    from ara.docx_documents._dto import valid_integer
    from ara.docx_documents.storage import _document, _snapshot
    from ara.models import DocxEditorCheckpoint, DocxEditReceipt

    attempt = actor.state.active
    handle = attempt.handle
    with _session(registry._runtime) as session:
        doc = _snapshot(_document(session, registry._runtime, actor.document_id))
        registry._ensure_live(actor)
        # Receipt is authoritative independently of someone else's draft body.
        row = session.get(DocxEditReceipt, (actor.document_id, handle.operation_id))
        committed = _committed(doc, row, handle) if row is not None else None
        fence = session.execute(
            select(
                DocxEditorCheckpoint.checkpoint_revision,
                DocxEditorCheckpoint.phase,
                DocxEditorCheckpoint.format_version,
                DocxEditorCheckpoint.last_request_id,
                DocxEditorCheckpoint.last_request_sha256,
                DocxEditorCheckpoint.checkpoint_metadata,
            ).where(DocxEditorCheckpoint.document_id == actor.document_id)
        ).one_or_none()
        if fence is not None and (
            not valid_integer(fence.checkpoint_revision, 1, MAX_REVISION)
            or type(fence.format_version) is not int
            or fence.format_version != 1
            or type(fence.phase) is not str
            or fence.phase not in ("empty", "working", "pending")
        ):
            raise ValueError("Invalid stored save fence")
        revision, phase = (fence.checkpoint_revision, fence.phase) if fence else (0, "absent")
        metadata = fence.checkpoint_metadata if fence else None
        pending = metadata.get("pending") if type(metadata) is dict else None
        own_pending = (
            phase == "pending"
            and revision == handle.prepared_checkpoint_revision
            and type(pending) is dict
            and pending.get("operation_id") == str(handle.operation_id)
            and pending.get("request_sha256") == handle.request_sha256
        )
        valid_pending = False
        if own_pending:
            cp = session.get(DocxEditorCheckpoint, actor.document_id)
            _legacy(session, actor.document_id, cp)
            valid_pending = _matches(_record(cp), handle)
        completed = (
            committed is not None
            and phase == "working"
            and revision == handle.prepared_checkpoint_revision + 1
            and fence.last_request_id is not None
            and fence.last_request_sha256
            == _control_fingerprint("finalize", handle, fence.last_request_id)
        )
        if completed:
            cp = _record(session.get(DocxEditorCheckpoint, actor.document_id))
            FinalizedSave(CheckpointSnapshot(doc, cp), committed.receipt, handle)
        base_match = (doc.storage_revision, doc.current_sha256) == (
            handle.base_storage_revision,
            handle.base_sha256,
        )
        if committed is not None:
            save_state = "committed" if committed.current_matches_receipt else "committed_outdated"
            head_matches = committed.current_matches_receipt
        elif valid_pending:
            save_state = (
                "conflict"
                if not base_match
                else "exhausted"
                if revision == MAX_REVISION or handle.base_storage_revision == MAX_REVISION
                else "ready"
            )
            head_matches = base_match
        else:
            save_state, head_matches = "superseded", base_match
        unchanged = not attempt.recovered and (revision, phase) == (
            actor.state.checkpoint_revision,
            actor.state.checkpoint_phase,
        )
        own = valid_pending or completed or (committed is None and unchanged)
        return registry._view(
            actor,
            Observation(summary(doc), revision, phase),
            active_matches=own,
            active_head_matches=head_matches,
            active_save_state=save_state,
        )
