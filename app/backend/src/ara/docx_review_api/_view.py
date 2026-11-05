"""Detached presentation with scope and preference revision rechecked after decode."""

import json

from sqlalchemy import select

from ara.docx_analysis.presentation import present
from ara.docx_analysis.storage_codec._verification import verification_scope
from ara.docx_analysis_api import _wire as analysis_wire
from ara.docx_analysis_runs import _storage
from ara.docx_review_preferences import _reads
from ara.docx_review_preferences._models import fail
from ara.docx_review_resolution._load import load_inputs
from ara.docx_review_resolution._resolve import resolve
from ara.models import DocxAnalysisRun as Run
from ara.models import DocxDocument

from . import _wire


def get_review(runtime, document_id, run_id=None):
    with _reads.transaction(runtime, document_id) as session:
        preferences = _reads.snapshot(session, document_id)
        query = select(*_storage.columns(), Run.error_code, Run.result_sha256).where(
            Run.document_id == document_id
        )
        query = (
            query.where(Run.id == run_id)
            if run_id is not None
            else query.where(Run.status == "succeeded").order_by(Run.accepted_order.desc()).limit(1)
        )
        row = session.execute(query).mappings().one_or_none()
        if row is None:
            fail("not_found")
        summary, error_code = _storage.summary(row), row["error_code"]
        origin = _reads.records(session, document_id, summary.run_id, row["result_sha256"])
        inputs = load_inputs(session, preferences, origin)
    records = tuple((o.source, o.attempt, o.result) for o in (inputs.target, *inputs.origins))
    with verification_scope(records):
        resolution = resolve(inputs)
        try:
            verified = present(
                origin.source,
                origin.attempt,
                origin.result,
                disabled_types=preferences.disabled_types,
                show_questions=preferences.show_questions,
                hidden_keys=resolution.hidden_keys,
                show_hidden=preferences.show_hidden,
            )
            view = json.loads(verified.wire_json)
        except Exception:
            fail("storage_error")
    with _reads.transaction(runtime, document_id) as session:
        if _reads.snapshot(session, document_id).revision != preferences.revision:
            fail("preferences_conflict")
        revision, digest = session.execute(
            select(DocxDocument.storage_revision, DocxDocument.current_sha256).where(
                DocxDocument.id == document_id
            )
        ).one()
    return dict(
        schema_version=_wire.VERSION,
        run=analysis_wire.run(summary, error_code),
        preferences=_wire.preferences(preferences),
        view=view,
        view_sha256=verified.view_sha256,
        current_storage_revision=str(revision),
        current_sha256=digest,
        matches_saved_document=(summary.storage_revision, summary.source_sha256)
        == (revision, digest),
        fixture=summary.execution_kind == "fixture",
    )
