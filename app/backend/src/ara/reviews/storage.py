"""Serialized, owner-scoped review chains with parent-based idempotent retries."""

import hashlib
import json
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ara.analysis_contract import validate_request, validate_result
from ara.analysis_contract.models import AnalysisResult
from ara.documents.runtime import DocumentRuntime
from ara.documents.storage import DocumentError, _not_found
from ara.models import AnalysisRun, Document, Project, ReviewRevision
from ara.reviews.schemas import GroupDecision, PutReview, ReviewResponse


@contextmanager
def _transaction(runtime: DocumentRuntime):
    try:
        with Session(runtime.engine) as session, session.begin():
            yield session
    except DocumentError:
        raise
    except OperationalError:
        raise DocumentError(
            503, "storage_unavailable", "Review storage is unavailable", True
        ) from None
    except Exception:
        # Covers corrupt persisted payloads and commit failures after rollback.
        raise DocumentError(500, "storage_error", "Review storage operation failed") from None


def _locked_run(session: Session, runtime: DocumentRuntime, run_id: UUID) -> AnalysisRun:
    # Match worker order: run -> document -> project. The run lock serializes
    # readers/writers; shared scope locks keep transfers out until commit.
    run = session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.id == run_id, AnalysisRun.owner_id == runtime.user_id)
        .with_for_update()
    )
    if run is None:
        raise _not_found()
    document = session.scalar(
        select(Document)
        .where(Document.id == run.document_id, Document.project_id == runtime.project_id)
        .with_for_update(read=True)
    )
    if document is None:
        raise _not_found()
    project = session.scalar(
        select(Project)
        .where(Project.id == document.project_id, Project.owner_id == runtime.user_id)
        .with_for_update(read=True)
    )
    if project is None:
        raise _not_found()
    if run.status != "succeeded":
        raise DocumentError(409, "review_not_ready", "Analysis is not ready for review")
    return run


def _source(run: AnalysisRun) -> tuple[AnalysisResult, str]:
    request = validate_request(run.request_payload)
    validated = validate_result(
        run.result_payload, request=request, has_import_omissions=run.has_import_omissions
    )
    # validate_result links result to request; also bind that saved request to
    # the relational run so a mutually consistent but unrelated pair is rejected.
    if (
        request.run_id != str(run.id)
        or request.base_document.document_id != str(run.document_id)
        or request.base_document.version_id != str(run.base_version_id)
        or request.context.revision_id != str(run.context_revision_id)
        or request.mode != run.mode
        or run.execution_mode != "fixture"
    ):
        raise ValueError("Invalid saved analysis identity")
    canonical = json.dumps(
        run.result_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return validated.result, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _revisions(run: AnalysisRun):
    return select(ReviewRevision).where(
        ReviewRevision.run_id == run.id, ReviewRevision.owner_id == run.owner_id
    )


def _result_changed() -> DocumentError:
    return DocumentError(409, "review_result_changed", "Analysis result has changed")


def _head(session: Session, run: AnalysisRun, fingerprint: str) -> ReviewRevision | None:
    # Check the entire chain, including historical reads and retries. No stored
    # edit may ever be interpreted against a different source result.
    changed = session.scalar(
        _revisions(run).where(ReviewRevision.result_fingerprint != fingerprint).limit(1)
    )
    if changed is not None:
        raise _result_changed()
    return session.scalar(_revisions(run).order_by(ReviewRevision.revision_number.desc()).limit(1))


def _canonical_decisions(body: PutReview, source: AnalysisResult) -> list[dict]:
    decisions = {decision.group_id: decision for decision in body.decisions}
    if decisions.keys() != {group.id for group in source.change_groups}:
        raise DocumentError(422, "validation_error", "Invalid request")
    result = []
    for group in source.change_groups:
        decision = decisions[group.id]
        for edit in decision.edits:
            if edit.patch_index >= len(group.patches) or edit.new_block_index >= len(
                group.patches[edit.patch_index].new_blocks
            ):
                raise DocumentError(422, "validation_error", "Invalid request")
        snapshot = decision.model_dump(mode="json")
        snapshot["edits"].sort(key=lambda edit: (edit["patch_index"], edit["new_block_index"]))
        result.append(snapshot)
    return result


def _response(
    run: AnalysisRun, source: AnalysisResult, fingerprint: str, revision: ReviewRevision | None
) -> ReviewResponse:
    return ReviewResponse(
        run_id=run.id,
        document_id=run.document_id,
        base_version_id=run.base_version_id,
        context_revision_id=run.context_revision_id,
        execution_mode=run.execution_mode,
        revision_id=revision.id if revision is not None else None,
        parent_revision_id=revision.parent_revision_id if revision is not None else None,
        revision_number=revision.revision_number if revision is not None else 0,
        created_at=revision.created_at if revision is not None else None,
        result_fingerprint=fingerprint,
        decisions=(
            revision.decisions
            if revision is not None
            else [
                GroupDecision(group_id=group.id, decision="pending", edits=[])
                for group in source.change_groups
            ]
        ),
    ).model_copy(deep=True)


def read_review(
    runtime: DocumentRuntime, run_id: UUID, *, revision_id: UUID | None = None
) -> ReviewResponse:
    with _transaction(runtime) as session:
        run = _locked_run(session, runtime, run_id)
        source, fingerprint = _source(run)
        revision = _head(session, run, fingerprint)
        if revision_id is not None:
            revision = session.scalar(_revisions(run).where(ReviewRevision.id == revision_id))
            if revision is None:
                raise _not_found()
        response = _response(run, source, fingerprint, revision)
    return response


def save_review(runtime: DocumentRuntime, run_id: UUID, body: PutReview) -> ReviewResponse:
    with _transaction(runtime) as session:
        run = _locked_run(session, runtime, run_id)
        source, fingerprint = _source(run)
        head = _head(session, run, fingerprint)
        if body.expected_result_fingerprint != fingerprint:
            raise _result_changed()
        decisions = _canonical_decisions(body, source)
        parent_id = UUID(body.expected_revision_id) if body.expected_revision_id else None
        child = session.scalar(
            _revisions(run).where(ReviewRevision.parent_revision_id == parent_id)
        )
        if child is not None:
            if child.result_fingerprint != fingerprint or child.decisions != decisions:
                raise DocumentError(409, "review_conflict", "Review revision has changed")
            response = _response(run, source, fingerprint, child)
        else:
            if parent_id != (head.id if head is not None else None):
                raise DocumentError(409, "review_conflict", "Review revision has changed")
            revision = ReviewRevision(
                run_id=run.id,
                owner_id=runtime.user_id,
                parent_revision_id=parent_id,
                revision_number=head.revision_number + 1 if head is not None else 1,
                result_fingerprint=fingerprint,
                decisions=decisions,
            )
            session.add(revision)
            session.flush()
            response = _response(run, source, fingerprint, revision)
    # Successful commit precedes returning the detached response, including replay.
    return response
