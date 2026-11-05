"""Atomic owner-scoped enqueue and immutable snapshot reads, without execution."""

import hashlib
import json
from contextlib import contextmanager
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ara.analysis_contract import validate_request
from ara.analysis_contract.models import BaseDocument
from ara.documents.runtime import DocumentRuntime
from ara.documents.storage import DocumentError, _not_found
from ara.models import AnalysisRun, ContextRevision, Document, DocumentVersion, Project
from ara.runs.schemas import CreateRun, RunError, RunResponse

UNSUPPORTED_DESCRIPTION = "[Unsupported block retained in source version]"
IDEMPOTENCY_CONSTRAINT = "uq_analysis_runs_owner_key"
RUN_ERROR_MESSAGES = {
    "deadline_exceeded": "Analysis execution deadline exceeded",
    "attempts_exhausted": "Analysis execution attempts exhausted",
    "access_revoked": "Analysis source access revoked",
    "invalid_request": "Invalid saved analysis request",
    "invalid_result": "Invalid analysis result",
}


@contextmanager
def _storage_errors():
    try:
        yield
    except DocumentError:
        raise
    except OperationalError:
        raise DocumentError(
            503, "storage_unavailable", "Analysis storage is unavailable", True
        ) from None
    except Exception:
        # Includes validation of corrupt stored data and failures during commit.
        raise DocumentError(500, "storage_error", "Analysis storage operation failed") from None


@contextmanager
def _transaction(runtime: DocumentRuntime):
    with Session(runtime.engine) as session, session.begin():
        project = session.scalar(
            select(Project.id)
            .where(Project.id == runtime.project_id, Project.owner_id == runtime.user_id)
            .with_for_update(read=True)
        )
        if project is None:
            raise _not_found()
        yield session


def _document(session: Session, runtime: DocumentRuntime, document_id: UUID) -> None:
    document = session.scalar(
        select(Document.id)
        .where(Document.id == document_id, Document.project_id == runtime.project_id)
        .with_for_update(read=True)
    )
    if document is None:
        raise _not_found()


def _source(
    session: Session, runtime: DocumentRuntime, document_id: UUID, body: CreateRun
) -> DocumentVersion:
    _document(session, runtime, document_id)
    version = session.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.id == UUID(body.base_version_id),
        )
        .with_for_update(read=True)
    )
    if version is None:
        raise _not_found()
    return version


def request_fingerprint(document_id: UUID, body: CreateRun) -> str:
    payload = {"document_id": str(document_id), **body.model_dump(mode="json")}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _response(run: AnalysisRun) -> RunResponse:
    return RunResponse(
        run_id=run.id,
        document_id=run.document_id,
        base_version_id=run.base_version_id,
        context_revision_id=run.context_revision_id,
        mode=run.mode,
        status=run.status,
        execution_mode=run.execution_mode,
        created_at=run.created_at,
        request=validate_request(run.request_payload),
        has_import_omissions=run.has_import_omissions,
        attempt_count=run.attempt_count,
        result=run.result_payload if run.status == "succeeded" else None,
        incomplete_review=run.incomplete_review if run.status == "succeeded" else None,
        error=(
            RunError(code=run.error_code, message=RUN_ERROR_MESSAGES[run.error_code])
            if run.status == "failed"
            else None
        ),
    )


def _previous(session: Session, runtime: DocumentRuntime, key: str) -> AnalysisRun | None:
    return session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.owner_id == runtime.user_id, AnalysisRun.idempotency_key == key
        )
    )


def _replay(run: AnalysisRun, fingerprint: str) -> RunResponse:
    if run.request_fingerprint != fingerprint:
        raise DocumentError(
            409, "idempotency_conflict", "Creation key was used for another request"
        )
    return _response(run)


def _insert(
    session: Session,
    runtime: DocumentRuntime,
    document_id: UUID,
    version: DocumentVersion,
    body: CreateRun,
    key: str,
    fingerprint: str,
) -> RunResponse:
    run_id, context_id = uuid4(), uuid4()
    # Validate the stored source before replacing unsupported text, so malformed
    # internal blocks cannot silently turn into valid queued inputs.
    base = BaseDocument.model_validate(
        {"document_id": str(document_id), "version_id": str(version.id), "blocks": version.blocks}
    )
    has_unsupported = False
    for block in base.blocks:
        if block.kind == "unsupported":
            block.text = UNSUPPORTED_DESCRIPTION
            has_unsupported = True
    if not isinstance(version.import_omissions, list):
        raise ValueError("Invalid stored omissions")
    items = [item.model_dump(mode="json") for item in body.context_items]
    snapshot = validate_request(
        {
            "contract_version": "0.1.0",
            "run_id": str(run_id),
            "mode": body.mode,
            "base_document": base.model_dump(mode="json"),
            "context": {"revision_id": str(context_id), "items": items},
        }
    )
    session.add(
        ContextRevision(
            id=context_id, document_id=document_id, owner_id=runtime.user_id, items=items
        )
    )
    session.flush()
    run = AnalysisRun(
        id=run_id,
        owner_id=runtime.user_id,
        document_id=document_id,
        base_version_id=version.id,
        context_revision_id=context_id,
        mode=body.mode,
        status="queued",
        execution_mode="fixture",
        idempotency_key=key,
        request_fingerprint=fingerprint,
        request_payload=snapshot.model_dump(mode="json"),
        has_import_omissions=bool(version.import_omissions) or has_unsupported,
    )
    session.add(run)
    session.flush()
    return _response(run)


def create_run(
    runtime: DocumentRuntime, document_id: UUID, body: CreateRun, key: str
) -> RunResponse:
    with _storage_errors():
        fingerprint = request_fingerprint(document_id, body)
        try:
            with _transaction(runtime) as session:
                version = _source(session, runtime, document_id, body)
                previous = _previous(session, runtime, key)
                result = (
                    _replay(previous, fingerprint)
                    if previous is not None
                    else _insert(session, runtime, document_id, version, body, key, fingerprint)
                )
        except IntegrityError as error:
            # Only this named unique violation is a creation race. The failed
            # transaction (including its context) has already rolled back fully.
            if (
                getattr(error.orig, "sqlstate", None) != "23505"
                or getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                != IDEMPOTENCY_CONSTRAINT
            ):
                raise
            with _transaction(runtime) as session:
                _source(session, runtime, document_id, body)
                winner = _previous(session, runtime, key)
                if winner is None:
                    raise ValueError("Missing creation race winner") from None
                result = _replay(winner, fingerprint)
        # Both the normal path and race replay commit before returning.
        return result


def read_run(runtime: DocumentRuntime, run_id: UUID) -> RunResponse:
    with _storage_errors(), _transaction(runtime) as session:
        run = session.scalar(
            select(AnalysisRun)
            .join(Document, Document.id == AnalysisRun.document_id)
            .where(
                AnalysisRun.id == run_id,
                AnalysisRun.owner_id == runtime.user_id,
                Document.project_id == runtime.project_id,
            )
        )
        if run is None:
            raise _not_found()
        _document(session, runtime, run.document_id)
        result = _response(run)
    return result
