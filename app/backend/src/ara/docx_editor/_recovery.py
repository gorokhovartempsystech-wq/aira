"""A single passive transaction for package, checkpoint and receipt proof."""

from contextlib import contextmanager
from dataclasses import dataclass, field

from ara.docx_documents._dto import MAX_REVISION
from ara.docx_documents.checkpoint_models import CheckpointSnapshot
from ara.docx_documents.checkpoints import _legacy, _record
from ara.docx_documents.save_commit import _committed, _matches
from ara.docx_documents.save_models import SaveStatus
from ara.docx_documents.save_prepare import _prepared

from ._scope import Observation, summary


@dataclass(frozen=True, slots=True, repr=False)
class RecoverySource:
    document: object = field(repr=False)
    checkpoint: object = field(repr=False)
    handle: object = field(repr=False)
    status: object = field(repr=False)

    def observation(self):
        c = self.checkpoint
        return Observation(
            summary(self.document), c.checkpoint_revision if c else 0, c.phase if c else "absent"
        )


@contextmanager
def read_source(runtime, document_id, *, handle=None):
    from ara.documents.storage import _session
    from ara.docx_documents.storage import _document, _snapshot
    from ara.models import DocxEditorCheckpoint, DocxEditReceipt

    with _session(runtime) as session:
        doc = _snapshot(_document(session, runtime, document_id))
        row = session.get(DocxEditorCheckpoint, document_id)
        _legacy(session, document_id, row)
        c = _record(row) if row is not None else None
        pending = (
            _prepared(CheckpointSnapshot(doc, c)).handle if c and c.phase == "pending" else None
        )
        proof = handle if handle is not None else pending
        status = None
        if proof is not None:
            receipt = session.get(DocxEditReceipt, (document_id, proof.operation_id))
            if receipt is not None:
                committed = _committed(doc, receipt, proof)
                state = "committed" if committed.current_matches_receipt else "committed_outdated"
                status = SaveStatus(state, doc, proof, committed.receipt, None)
            else:
                state = "superseded"
                if c is not None and _matches(c, proof):
                    base_matches = (doc.storage_revision, doc.current_sha256) == (
                        proof.base_storage_revision,
                        proof.base_sha256,
                    )
                    state = (
                        "conflict"
                        if not base_matches
                        else "exhausted"
                        if c.checkpoint_revision == MAX_REVISION
                        or proof.base_storage_revision == MAX_REVISION
                        else "ready"
                    )
                status = SaveStatus(state, doc, proof, None, c.checkpoint_revision if c else None)
        yield RecoverySource(doc, c, pending, status)
