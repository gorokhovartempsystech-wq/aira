"""Checkpoint attempts survive unknown SQL outcomes until explicit reconciliation."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
from hashlib import sha256
from uuid import uuid4

from ara.docx_documents._dto import MAX_REVISION
from ara.docx_documents.checkpoint_fingerprints import checkpoint_fingerprint
from ara.docx_documents.checkpoints import put_checkpoint
from ara.docx_package.checkpoint import CheckpointMetadata, CheckpointOrigin, encode_metadata

from . import _models
from ._commands import fingerprint
from ._errors import editor_boundary, error, native_errors
from ._recovery import read_source
from ._scope import observe, summary


@dataclass(frozen=True, slots=True, repr=False)
class SaveTarget:
    registry_id: object
    document_id: object
    session_id: object
    command_sequence: int
    revision: int
    position_id: int
    sha256: str
    size_bytes: int
    selection: object = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class CheckpointAttempt:
    action: str
    command_id: object
    request_sha256: str
    expected_command_sequence: int
    expected_session_revision: int
    request_id: object
    expected_checkpoint_revision: int
    base_revision: int
    base_sha256: str
    data: bytes = field(repr=False)
    metadata: object = field(repr=False)
    put_sha256: str
    target: SaveTarget = field(repr=False)

    def descriptor(self):
        return _models.ActiveCommand(
            self.command_id,
            self.action,
            self.request_sha256,
            self.expected_command_sequence,
            self.expected_session_revision,
            "checkpoint_pending",
        )


@dataclass(frozen=True, slots=True)
class _Control:
    action: str
    value: object = None
    after: object = None


def _target(registry, actor, state, snapshot):
    return SaveTarget(
        registry._registry_id,
        actor.document_id,
        actor.session_id,
        state.command_sequence,
        snapshot.document.revision,
        snapshot.position_id,
        sha256(snapshot.document.data).hexdigest(),
        len(snapshot.document.data),
        deepcopy(snapshot.selection),
    )


def _binding(registry, actor, state, attempt):
    return _target(registry, actor, state, state.editor.snapshot()) == attempt.target


def _build(registry, actor, state, snapshot, action, command_id, digest):
    target = _target(registry, actor, state, snapshot)
    metadata = CheckpointMetadata(
        deepcopy(snapshot.selection),
        CheckpointOrigin(actor.session_id, target.revision, target.position_id),
    )
    with native_errors():
        wire = encode_metadata(
            metadata, data=snapshot.document.data, saved_sha256=state.base_sha256, phase="working"
        )
    request_id = uuid4()
    proof = checkpoint_fingerprint(
        "put",
        actor.document_id,
        state.checkpoint_revision,
        request_id,
        base_revision=state.base_revision,
        base_sha256=state.base_sha256,
        data=snapshot.document.data,
        metadata=wire,
    )
    return CheckpointAttempt(
        action,
        command_id,
        digest,
        state.command_sequence,
        target.revision,
        request_id,
        state.checkpoint_revision,
        state.base_revision,
        state.base_sha256,
        snapshot.document.data,
        metadata,
        proof,
        target,
    )


def matches(record, attempt):
    return (
        record is not None
        and record.phase == "working"
        and record.checkpoint_revision == attempt.expected_checkpoint_revision + 1
        and record.last_request_id == attempt.request_id
        and record.last_request_sha256 == attempt.put_sha256
        and record.base_storage_revision == attempt.base_revision
        and record.base_sha256 == attempt.base_sha256
        and record.working_data == attempt.data
        and record.working_sha256 == attempt.target.sha256
        and record.metadata == attempt.metadata
    )


def live_view(registry, actor):
    # A foreign empty/legacy fence is enough to classify conflict. Do not make
    # rescue of the local copy depend on opening somebody else's draft mode.
    with observe(registry._runtime, actor.document_id) as observation:
        registry._ensure_live(actor)
        state = actor.state
        unchanged = (observation.revision, observation.phase) == (
            state.checkpoint_revision,
            state.checkpoint_phase,
        )
        maybe_own = (
            observation.revision == state.checkpoint_revision + 1 and observation.phase == "working"
        )
        if unchanged or not maybe_own:
            return registry._view(actor, observation, active_matches=unchanged)
    # No outer transaction while acquiring another connection's locks. This
    # second read is the entire authoritative snapshot, not joined with above.
    with read_source(registry._runtime, actor.document_id) as source:
        registry._ensure_live(actor)
        attempt = actor.state.active
        unchanged = (source.observation().revision, source.observation().phase) == (
            actor.state.checkpoint_revision,
            actor.state.checkpoint_phase,
        )
        return registry._view(
            actor,
            source.observation(),
            active_matches=unchanged or matches(source.checkpoint, attempt),
        )


def _release(registry, actor):
    with registry._index:
        registry._actors.pop((actor.document_id, actor.session_id))
        registry._opens.pop(actor.request[2])
        registry._budget.release(actor.session_id)


def _closed(registry, actor, mode, revision):
    return _models.ClosedEditor(
        registry._registry_id, actor.document_id, actor.session_id, mode, revision
    )


def _perform(registry, actor, *, fresh=False):
    attempt = actor.state.active
    if hasattr(attempt, "handle"):
        from ._save import perform

        return perform(registry, actor, fresh=fresh)
    if not _binding(registry, actor, actor.state, attempt):
        error("editor_error", 500)
    result = put_checkpoint(
        registry._runtime,
        document_id=actor.document_id,
        expected_checkpoint_revision=attempt.expected_checkpoint_revision,
        request_id=attempt.request_id,
        base_storage_revision=attempt.base_revision,
        base_sha256=attempt.base_sha256,
        data=attempt.data,
        metadata=attempt.metadata,
    )
    # SQL may have committed already. All failures here must keep the immutable attempt.
    with editor_boundary():
        result.__post_init__()
        result.document.__post_init__()
        result.checkpoint.__post_init__()
        if not matches(result.checkpoint, attempt):
            error("checkpoint_conflict")
        if (result.document.storage_revision, result.document.current_sha256) != (
            attempt.base_revision,
            attempt.base_sha256,
        ):
            error("docx_conflict")
        if not _binding(registry, actor, actor.state, attempt):
            error("editor_error", 500)
        if attempt.action == "close":
            reply = _closed(registry, actor, "checkpoint", result.checkpoint.checkpoint_revision)
            _release(registry, actor)
            return reply
        state = actor.state
        receipt = _models.CommandReceipt(
            attempt.command_id,
            attempt.request_sha256,
            attempt.action,
            attempt.expected_command_sequence,
            attempt.expected_session_revision,
            state.command_sequence + 1,
            attempt.target.revision,
            attempt.target.position_id,
        )
        future = replace(
            state,
            checkpoint_revision=result.checkpoint.checkpoint_revision,
            checkpoint_phase="working",
            command_sequence=state.command_sequence + 1,
            last_command=receipt,
            active=None,
            saved=None,
        )
        if attempt.action == "save":
            from ._save import make_target

            future = replace(
                future,
                saved=make_target(registry, actor, attempt, result.document.storage_revision),
            )
        from ._scope import Observation

        reply = registry._view(
            actor,
            Observation(summary(result.document), result.checkpoint.checkpoint_revision, "working"),
            state=future,
        )
        with registry._index:
            actor.state = future
        return reply


def run(
    registry,
    *,
    action,
    document_id,
    session_id,
    command_id,
    expected_command_sequence,
    expected_session_revision,
    mode=None,
):
    with registry._index:
        actor = registry._actors.get((document_id, session_id))
    if actor is None:
        with observe(registry._runtime, document_id):
            error("editor_session_expired", 410)
    with actor.mutex, registry._heavy:
        # No durable call while this read transaction owns project/document locks.
        with observe(registry._runtime, document_id) as observation:
            registry._ensure_live(actor)
            with editor_boundary():
                state = actor.state
                snapshot = state.editor.snapshot()
                active, last = state.active, state.last_command
                if action == "close" and mode == "release_local":
                    if (last is not None and last.command_id == command_id) or (
                        active is not None and active.command_id == command_id
                    ):
                        error("idempotency_conflict")
                    if (expected_command_sequence, expected_session_revision) != (
                        state.command_sequence,
                        snapshot.document.revision,
                    ):
                        error("stale_command")
                    release_reply = _closed(registry, actor, mode, None)
                    release = True
                else:
                    release = False
                    digest = fingerprint(
                        registry._registry_id,
                        document_id,
                        session_id,
                        command_id,
                        expected_command_sequence,
                        expected_session_revision,
                        _Control(action, mode if action == "close" else None),
                    )
                    if action == "reconcile":
                        if active is None:
                            if (
                                last is not None
                                and last.command_id == command_id
                                and last.action in ("checkpoint", "save")
                            ):
                                if (
                                    last.expected_command_sequence,
                                    last.expected_session_revision,
                                ) != (expected_command_sequence, expected_session_revision):
                                    error("idempotency_conflict")
                                return registry._view(actor, observation)
                            if state.handle is None:
                                error("editor_operation_missing")
                            if (expected_command_sequence, expected_session_revision) != (
                                state.command_sequence,
                                snapshot.document.revision,
                            ):
                                error("stale_command")
                            if state.command_sequence == MAX_REVISION:
                                error("revision_exhausted")
                            from ._save import build

                            active = build(
                                registry, actor, state, snapshot, command_id, digest, recovered=True
                            )
                        if active.command_id != command_id:
                            error("stale_command")
                        if (active.expected_command_sequence, active.expected_session_revision) != (
                            expected_command_sequence,
                            expected_session_revision,
                        ):
                            error("idempotency_conflict")
                    elif last is not None and last.command_id == command_id:
                        if (
                            last.request_sha256,
                            last.expected_command_sequence,
                            last.expected_session_revision,
                        ) != (digest, expected_command_sequence, expected_session_revision):
                            error("idempotency_conflict")
                        return registry._view(actor, observation)
                    elif active is not None:
                        if active.command_id != command_id:
                            error("editor_operation_pending")
                        if (
                            active.request_sha256,
                            active.expected_command_sequence,
                            active.expected_session_revision,
                        ) != (digest, expected_command_sequence, expected_session_revision):
                            error("idempotency_conflict")
                    else:
                        if (expected_command_sequence, expected_session_revision) != (
                            state.command_sequence,
                            snapshot.document.revision,
                        ):
                            error("stale_command")
                        if state.handle is not None:
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
                        if (
                            state.command_sequence == MAX_REVISION
                            or state.checkpoint_revision == MAX_REVISION
                        ):
                            error("revision_exhausted")
                        if action == "save" and snapshot.document.is_dirty:
                            from ._save import build

                            active = build(registry, actor, state, snapshot, command_id, digest)
                        else:
                            active = _build(
                                registry, actor, state, snapshot, action, command_id, digest
                            )
        if release:
            _release(registry, actor)
            return release_reply
        if state.active is None:
            with registry._index:
                actor.state = replace(state, active=active)
        fresh = state.active is None and getattr(active, "recovered", True) is False
        return _perform(registry, actor, fresh=fresh)
