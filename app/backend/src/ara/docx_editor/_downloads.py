"""Passive exact package reads; rescue is independent of save receipt proof."""

from hashlib import sha256
from uuid import UUID

from ara.docx_documents._dto import MAX_REVISION, _hash, valid_integer

from ._errors import editor_boundary, error, validate
from ._models import RecoveryTarget, WorkingTarget
from ._scope import scoped_document


def working(registry, document_id, session_id, sequence, revision, digest):
    validate(
        type(document_id) is UUID
        and type(session_id) is UUID
        and valid_integer(sequence, 0, MAX_REVISION)
        and valid_integer(revision, 0, MAX_REVISION)
        and _hash(digest)
    )
    with registry._index:
        actor = registry._actors.get((document_id, session_id))
    if actor is None:
        with scoped_document(registry._runtime, document_id):
            error("editor_session_expired", 410)
    with actor.mutex, registry._heavy:
        with scoped_document(registry._runtime, document_id):
            registry._ensure_live(actor)
            state = actor.state
            with editor_boundary():
                snapshot = state.editor.snapshot().document
                if (
                    state.command_sequence,
                    snapshot.revision,
                    sha256(snapshot.data).hexdigest(),
                ) != (
                    sequence,
                    revision,
                    digest,
                ):
                    error("stale_command")
                target = WorkingTarget(
                    registry._registry_id,
                    document_id,
                    session_id,
                    sequence,
                    revision,
                    digest,
                    snapshot.data,
                )
        return target


def recovery(registry, document_id, revision, digest):
    from ara.docx_documents.checkpoints import _legacy, _record
    from ara.models import DocxEditorCheckpoint

    validate(
        type(document_id) is UUID and valid_integer(revision, 0, MAX_REVISION) and _hash(digest)
    )
    with registry._heavy, scoped_document(registry._runtime, document_id) as session:
        row = session.get(DocxEditorCheckpoint, document_id)
        _legacy(session, document_id, row)
        record = _record(row) if row is not None else None
        if (
            record is None
            or record.phase == "empty"
            or (record.checkpoint_revision, record.working_sha256) != (revision, digest)
        ):
            error("checkpoint_conflict")
        with editor_boundary():
            target = RecoveryTarget(document_id, revision, digest, record.working_data)
    return target
