"""Scoped read-only operations; restore immutable results outside SQL locks."""

import json
from contextlib import contextmanager
from dataclasses import fields, replace

from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError, TimeoutError
from sqlalchemy.orm import Session

from ara.documents.storage import DocumentError
from ara.docx_analysis.storage_codec import (
    AttemptBundle,
    ResultBundle,
    SourceBundle,
    restore_result,
)
from ara.docx_analysis_runs import _storage
from ara.docx_analysis_runs._models import RunSummary
from ara.docx_analysis_worker.supervisor.database import OPTIONS
from ara.models import DocxAnalysisAttempt as Attempt
from ara.models import DocxAnalysisResult as Result
from ara.models import DocxAnalysisRun as Run
from ara.models import DocxAnalysisSource as Source
from ara.models import DocxDocument


def fail(code, status=500):
    messages = {
        "storage_error": "Analysis storage operation failed",
        "storage_unavailable": "Analysis storage is unavailable",
        "not_found": "Document or analysis run not found",
        "result_not_ready": "Analysis result is not ready",
        "recovery_required": "Analysis runtime recovery is required",
        "analysis_busy": "Analysis is handling another request",
        "idempotency_conflict": "Analysis request does not match",
    }
    raise DocumentError(status, code, messages[code], status == 503)


def read_runtime(runtime):
    # Lazy dedicated pool; never modifies the caller's engine or global settings.
    engine = create_engine(
        runtime.engine.url,
        pool_size=2,
        max_overflow=0,
        pool_timeout=0.5,
        echo=False,
        echo_pool=False,
        hide_parameters=True,
        connect_args={"connect_timeout": 2, "options": OPTIONS},
    )
    return replace(runtime, engine=engine)


@contextmanager
def transaction(runtime, document_id):
    try:
        with Session(runtime.engine) as session, session.begin():
            _storage.scope(session, runtime, document_id)
            yield session
    except DocumentError:
        raise
    except (OperationalError, TimeoutError):
        fail("storage_unavailable", 503)
    except Exception:
        fail("storage_error")


def scope_check(runtime, document_id):
    with transaction(runtime, document_id) as session:
        row = session.execute(
            select(DocxDocument.storage_revision, DocxDocument.current_sha256).where(
                DocxDocument.id == document_id
            )
        ).one()
    return row.storage_revision, row.current_sha256


def metadata(row):
    summary = _storage.summary(row)
    return summary, row["error_code"]


def get_run(runtime, document_id, run_id):
    with transaction(runtime, document_id) as session:
        row = (
            session.execute(
                select(*_storage.columns(), Run.error_code).where(
                    Run.document_id == document_id, Run.id == run_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            fail("not_found", 404)
        return metadata(row)


def get_request(runtime, document_id, key):
    with transaction(runtime, document_id) as session:
        row = (
            session.execute(
                select(*_storage.columns(), Run.error_code).where(
                    Run.document_id == document_id, Run.client_request_id == key
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            fail("not_found", 404)
        return metadata(row)


def get_result(runtime, document_id, run_id=None):
    with transaction(runtime, document_id) as session:
        query = select(Run).where(Run.document_id == document_id)
        query = (
            query.where(Run.id == run_id)
            if run_id is not None
            else query.where(Run.status == "succeeded").order_by(Run.accepted_order.desc()).limit(1)
        )
        run = session.scalar(query)
        if run is None:
            fail("not_found", 404)
        if run.status != "succeeded":
            fail("result_not_ready", 409)
        summary = RunSummary(
            **{
                f.name: run.id if f.name == "run_id" else getattr(run, f.name)
                for f in fields(RunSummary)
            }
        )
        source = session.get(Source, (document_id, run.source_sha256))
        attempt = session.get(Attempt, run.attempt_id)
        result = session.get(Result, run.id)
        if (
            source is None
            or attempt is None
            or result is None
            or (attempt.document_id, attempt.run_id) != (document_id, run.id)
            or (result.document_id, result.attempt_id, result.result_sha256)
            != (document_id, attempt.id, run.result_sha256)
        ):
            fail("storage_error")
        source_bundle = SourceBundle(
            **{
                f.name: source.source_data if f.name == "source_data" else getattr(run, f.name)
                for f in fields(SourceBundle)
            }
        )
        attempt_bundle = AttemptBundle(attempt.id, attempt.request_data, attempt.request_sha256)
        result_bundle = ResultBundle(
            **{f.name: getattr(result, f.name) for f in fields(ResultBundle)}
        )
        error_code = run.error_code
    try:
        verified = restore_result(source_bundle, attempt_bundle, result_bundle)
        public = json.loads(verified.wire_json)
        del public["private_provenance"]
    except Exception:
        fail("storage_error")
    revision, digest = scope_check(runtime, document_id)
    return summary, error_code, public, verified.result_sha256, revision, digest
