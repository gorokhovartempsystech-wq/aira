"""PostgreSQL queue with fenced attempts; the adapter runs outside all transactions."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ara.analysis_contract import ContractValidationError, validate_request, validate_result
from ara.models import AnalysisAttempt, AnalysisRun, Document, Project
from ara.runs.storage import _storage_errors

from .fixture import fixture_result
from .types import Claim, WorkerSettings, WorkOutcome


def _clock(session):
    return session.scalar(select(func.clock_timestamp()))


def _scope(session, run):
    # All worker transitions lock one run, then its document, then its project.
    # Shared scope locks allow workers for the same project to proceed together,
    # but prevent transfers/owner changes until the transition commits.
    document = session.scalar(
        select(Document).where(Document.id == run.document_id).with_for_update(read=True)
    )
    if document is None:
        return None
    project = session.scalar(
        select(Project).where(Project.id == document.project_id).with_for_update(read=True)
    )
    return project.id if project is not None and project.owner_id == run.owner_id else None


def _metadata(duration_ms=0):
    return {
        "adapter": "fixture",
        "adapter_version": "1",
        "model": None,
        "prompt_version": None,
        "model_calls": 0,
        "duration_ms": duration_ms,
    }


def _finish_history(attempt, now, status, code=None):
    attempt.status = status
    attempt.finished_at = now
    attempt.error_code = code
    attempt.execution_metadata = _metadata(
        max(0, (now - attempt.started_at).total_seconds() * 1000)
    )


def _clear_active(run):
    run.active_attempt_id = None
    run.lease_expires_at = None


def _terminal(run, now, code):
    _clear_active(run)
    run.status = "failed"
    run.completed_at = now
    run.error_code = code


def _claim_locked(session, run, settings):
    project_id = _scope(session, run)
    now = _clock(session)
    if run.status == "running":
        # Recheck after acquiring scope locks with a fresh PostgreSQL clock.
        if run.lease_expires_at > now and run.deadline_at > now:
            return None
        attempt = session.get(AnalysisAttempt, run.active_attempt_id)
        _finish_history(attempt, now, "expired", "lease_expired")
        _clear_active(run)
        run.status = "queued"
    if project_id is None:
        _terminal(run, now, "access_revoked")
        return None
    if run.deadline_at is not None and run.deadline_at <= now:
        _terminal(run, now, "deadline_exceeded")
        return None
    if run.max_attempts is not None and run.attempt_count >= run.max_attempts:
        _terminal(run, now, "attempts_exhausted")
        return None
    if run.available_at > now:
        return None
    try:
        request = validate_request(run.request_payload)
    except ContractValidationError:
        _terminal(run, _clock(session), "invalid_request")
        return None
    now = _clock(session)
    if run.deadline_at is None:
        run.max_attempts = settings.max_attempts
        run.deadline_at = now + timedelta(seconds=settings.run_timeout_seconds)
    if run.deadline_at <= now:
        _terminal(run, now, "deadline_exceeded")
        return None
    expiry = min(now + timedelta(seconds=settings.lease_seconds), run.deadline_at)
    attempt = AnalysisAttempt(
        id=uuid4(),
        run_id=run.id,
        attempt_number=run.attempt_count + 1,
        project_id=project_id,
        started_at=now,
        lease_expires_at=expiry,
        status="running",
        retry_delay_seconds=settings.retry_delay_seconds,
        execution_metadata=_metadata(),
    )
    session.add(attempt)
    # Insert the referenced attempt before assigning the cyclic active-attempt FK.
    session.flush()
    run.attempt_count = attempt.attempt_number
    run.active_attempt_id = attempt.id
    run.lease_expires_at = expiry
    run.status = "running"
    return Claim(
        run.id,
        attempt.id,
        attempt.attempt_number,
        request,
        run.has_import_omissions,
        expiry,
        run.deadline_at,
    )


def claim_next(engine, *, settings=None) -> Claim | None:
    settings = WorkerSettings() if settings is None else settings
    result = None
    with _storage_errors(), Session(engine, autoflush=False) as session, session.begin():
        visited = []
        for _ in range(100):
            now = func.clock_timestamp()
            candidate = or_(
                and_(
                    AnalysisRun.status == "queued",
                    or_(
                        AnalysisRun.available_at <= now,
                        AnalysisRun.deadline_at <= now,
                        AnalysisRun.attempt_count >= AnalysisRun.max_attempts,
                        ~select(Project.id)
                        .join(Document, Document.project_id == Project.id)
                        .where(
                            Document.id == AnalysisRun.document_id,
                            Project.owner_id == AnalysisRun.owner_id,
                        )
                        .exists(),
                    ),
                ),
                and_(
                    AnalysisRun.status == "running",
                    or_(
                        AnalysisRun.lease_expires_at <= now,
                        AnalysisRun.deadline_at <= now,
                    ),
                ),
            )
            run = session.scalar(
                select(AnalysisRun)
                .where(candidate, AnalysisRun.id.not_in(visited))
                .order_by(AnalysisRun.created_at, AnalysisRun.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if run is None:
                break
            visited.append(run.id)
            result = _claim_locked(session, run, settings)
            session.flush()
            if result is not None:
                break
    # The context manager commits before any detached claim escapes.
    return result


def _live(run, claim, now):
    return (
        run is not None
        and run.status == "running"
        and run.active_attempt_id == claim.attempt_id
        and run.lease_expires_at > now
        and run.deadline_at > now
    )


def _fail_locked(run, attempt, now, code):
    _finish_history(attempt, now, "failed", code)
    _clear_active(run)
    if code in ("invalid_request", "invalid_result", "access_revoked"):
        _terminal(run, now, code)
        return "failed"
    available = now + timedelta(seconds=attempt.retry_delay_seconds)
    if available >= run.deadline_at:
        _terminal(run, now, "deadline_exceeded")
        return "failed"
    if run.attempt_count >= run.max_attempts:
        _terminal(run, now, "attempts_exhausted")
        return "failed"
    run.status = "queued"
    run.available_at = available
    return "retry_scheduled"


def _finish(engine, claim, *, payload=None, code=None):
    outcome = "stale"
    with _storage_errors(), Session(engine, autoflush=False) as session, session.begin():
        run = session.scalar(
            select(AnalysisRun).where(AnalysisRun.id == claim.run_id).with_for_update()
        )
        if not _live(run, claim, _clock(session)):
            return outcome
        project_id = _scope(session, run)
        attempt = session.scalar(
            select(AnalysisAttempt)
            .where(AnalysisAttempt.run_id == run.id, AnalysisAttempt.id == claim.attempt_id)
            .with_for_update()
        )
        now = _clock(session)
        if not _live(run, claim, now):
            return outcome
        if project_id is None or project_id != attempt.project_id:
            outcome = _fail_locked(run, attempt, now, "access_revoked")
        elif code is not None:
            outcome = _fail_locked(run, attempt, now, code)
        else:
            validated = None
            try:
                validated = validate_result(
                    payload,
                    request=run.request_payload,
                    has_import_omissions=run.has_import_omissions,
                )
            except ContractValidationError as error:
                code = error.code
            # Include serialization in validation time, before checking the final clock.
            saved = validated.result.model_dump(mode="json") if validated else None
            now = _clock(session)
            if not _live(run, claim, now):
                return "stale"
            if validated is None:
                outcome = _fail_locked(run, attempt, now, code)
            else:
                _finish_history(attempt, now, "succeeded")
                _clear_active(run)
                run.status = "succeeded"
                run.completed_at = now
                run.result_payload = saved
                run.incomplete_review = validated.incomplete_review
                outcome = "succeeded"
    return outcome


def complete_attempt(engine, claim, payload) -> bool:
    return _finish(engine, claim, payload=payload) == "succeeded"


def _validate_code(code):
    if code not in ("adapter_error", "adapter_timeout", "invalid_result"):
        raise ValueError("Invalid worker failure code")


def fail_attempt(engine, claim, *, code) -> bool:
    _validate_code(code)
    return _finish(engine, claim, code=code) != "stale"


def run_once(engine, *, adapter=None, settings=None) -> WorkOutcome:
    claim = claim_next(engine, settings=settings)
    if claim is None:
        return WorkOutcome("idle", None)
    adapter = fixture_result if adapter is None else adapter
    code = None
    payload = None
    request = claim.request.model_copy(deep=True)
    try:
        payload = adapter(request)
    except TimeoutError:
        code = "adapter_timeout"
    except Exception:
        code = "adapter_error"
    # Storage exceptions are deliberately outside the adapter exception boundary.
    return WorkOutcome(_finish(engine, claim, payload=payload, code=code), claim.run_id)
