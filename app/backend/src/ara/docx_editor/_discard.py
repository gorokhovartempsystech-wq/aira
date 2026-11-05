"""Passive plan preparation and dispatch to the existing durable CAS protocol."""

from ara.docx_documents.checkpoints import _legacy, _record, discard_checkpoint
from ara.docx_documents.save_reconcile import discard_pending

from . import _discard_wire
from ._errors import error
from ._scope import scoped_document, summary


def prepare(runtime, *, document_id, expected_checkpoint_revision, request_id):
    from ara.models import DocxEditorCheckpoint

    with scoped_document(runtime, document_id) as session:
        row = session.get(DocxEditorCheckpoint, document_id)
        _legacy(session, document_id, row)
        record = _record(row) if row is not None else None
        if (
            record is None
            or record.phase == "empty"
            or record.checkpoint_revision != expected_checkpoint_revision
        ):
            error("checkpoint_conflict")
        encoded = _discard_wire.encode_plan(document_id, record, request_id)
    return encoded


def execute(
    runtime, *, kind, document_id, request_id, handle=None, expected_checkpoint_revision=None
):
    from . import wire

    if kind == "working":
        snapshot = discard_checkpoint(
            runtime,
            document_id=document_id,
            expected_checkpoint_revision=expected_checkpoint_revision,
            request_id=request_id,
        )
        confirmation, matches = "not_checked", None
    else:
        result = discard_pending(runtime, handle=handle, request_id=request_id)
        snapshot = result.snapshot
        confirmation = "confirmed" if result.save_confirmed else "unconfirmed"
        matches = result.current_matches_receipt
    return wire._dump(
        dict(
            kind="discarded",
            document_id=str(document_id),
            checkpoint_revision=str(snapshot.checkpoint.checkpoint_revision),
            current=wire._summary(summary(snapshot.document)),
            save_confirmation=confirmation,
            current_matches_receipt=matches,
        ),
        65536,
    )
