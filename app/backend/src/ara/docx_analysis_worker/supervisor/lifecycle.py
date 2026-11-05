"""Exact scoped SQL jobs; anchors and physical execution belong to the supervisor."""

from datetime import timedelta

from sqlalchemy import select, text

from ara.documents.storage import DocumentError
from ara.docx_analysis.storage_codec import AttemptBundle, StorageCodecError, prepare_attempt
from ara.docx_analysis.storage_codec._records import LOWER_ERRORS
from ara.docx_analysis_runs import _lifecycle as old
from ara.docx_analysis_runs import _storage
from ara.docx_analysis_runs._lifecycle_models import WorkerClaim
from ara.docx_analysis_runs._lifecycle_storage import locked, same_source, state
from ara.models import DocxAnalysisAttempt as Attempt
from ara.models import DocxAnalysisRun as Run

from . import _sql as db
from .sql_models import ClaimReceipt, HeartbeatReceipt, QueuedRun

clock = _storage.clock


def _clean(session, owner):
    row = db.locked(session)
    db.owned(row, owner)
    if row.phase != "clean":
        db.fail()


def _identity(run, attempt, attempt_id, worker):
    return (
        attempt is not None
        and run.attempt_id == attempt_id
        and attempt.id == attempt_id
        and attempt.worker_instance_id == worker
        and attempt.claim_fence == 1
    )


def claim_exact(
    runtime,
    *,
    document_id,
    run_id,
    attempt_id,
    worker_instance_id,
    owner,
    limits=None,
    monotonic=None,
):
    _storage.context(runtime)
    for value in (document_id, run_id, attempt_id, worker_instance_id):
        db.uuid(value)
    db.owner(owner)
    limits = old.limits_checked(limits)
    with db.transaction(runtime.engine) as session:
        run, attempt, scope = locked(session, document_id, run_id, runtime=runtime)
        old.expire(run, scope, clock(session))
        _clean(session, owner)
        if run.status in old.TERMINAL or run.status == "cancel_requested":
            return ClaimReceipt(None, state(run))
        if run.status != "queued" and not _identity(run, attempt, attempt_id, worker_instance_id):
            db.fail()
    try:
        source = _storage.get_source(runtime, document_id=document_id, run_id=run_id, limits=limits)
        prepared = prepare_attempt(source, attempt_id=attempt_id, limits=limits)
    except (DocumentError, StorageCodecError, *LOWER_ERRORS) as error:
        if isinstance(error, DocumentError) and error.status == 503:
            raise
        code = (
            "analysis_limit_exceeded"
            if getattr(error, "code", None) in ("analysis_limit_exceeded", "codec_limit_exceeded")
            else "source_corrupt"
        )
        with db.transaction(runtime.engine) as session:
            run, attempt, scope = locked(session, document_id, run_id, runtime=runtime)
            _clean(session, owner)
            old.expire(run, scope, clock(session))
            if run.status == "queued" or (
                run.status == "running" and _identity(run, attempt, attempt_id, worker_instance_id)
            ):
                old.terminal(run, "failed", code, clock(session))
            result = ClaimReceipt(None, state(run))
        return result
    # Preparation is outside the lease. Sample before the transaction which grants it;
    # all lock/commit latency still consumes the conservative native budget.
    budget_started = monotonic() if monotonic is not None else None
    with db.transaction(runtime.engine) as session:
        run, attempt, scope = locked(session, document_id, run_id, runtime=runtime)
        _clean(session, owner)
        now = clock(session)
        old.expire(run, scope, now)
        if run.status in old.TERMINAL or run.status == "cancel_requested":
            return ClaimReceipt(None, state(run))
        if not same_source(session, run, source):
            old.terminal(run, "failed", "source_corrupt", clock(session))
            return ClaimReceipt(None, state(run))
        now = clock(session)
        if old.expire(run, scope, now):
            return ClaimReceipt(None, state(run))
        replayed = run.status == "running"
        if replayed:
            if not _identity(run, attempt, attempt_id, worker_instance_id):
                db.fail()
            raw = session.scalar(select(Attempt.request_data).where(Attempt.id == attempt.id))
            if raw != prepared.request_data or attempt.request_sha256 != prepared.request_sha256:
                db.fail("storage_error")
            bundle = AttemptBundle(attempt_id, raw, attempt.request_sha256)
        else:
            if run.status != "queued":
                db.fail()
            bundle = prepared
            session.add(
                Attempt(
                    id=attempt_id,
                    document_id=document_id,
                    run_id=run_id,
                    claim_fence=1,
                    worker_instance_id=worker_instance_id,
                    request_data=prepared.request_data,
                    request_sha256=prepared.request_sha256,
                    created_at=now,
                )
            )
            run.status, run.stage, run.fence = "running", "preparing_document", 1
            run.attempt_id = attempt_id
            run.started_at = run.heartbeat_at = run.updated_at = now
            run.lease_expires_at = min(now + timedelta(seconds=15), run.deadline_at)
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        claim = WorkerClaim(
            run_id,
            document_id,
            attempt_id,
            worker_instance_id,
            1,
            source,
            bundle,
            run.started_at,
            run.deadline_at,
            run.lease_expires_at,
        )
        result = ClaimReceipt(claim, state(run), replayed, None if replayed else budget_started)
    return result


def _heartbeat(runtime, claim, owner, stage, write):
    _storage.context(runtime)
    old.valid_claim(claim)
    db.owner(owner)
    if stage is not None and (type(stage) is not str or stage not in old.STAGES):
        _storage.fail("validation_error", 422)
    with db.transaction(runtime.engine) as session:
        run, attempt, scope = locked(session, claim.document_id, claim.run_id, runtime=runtime)
        row = db.locked(session)
        db.owned(row, owner)
        now = clock(session)
        old.expire(run, scope, now)
        accepted = (
            row.phase in ("armed", "drained")
            and (
                row.document_id,
                row.run_id,
                row.attempt_id,
                row.worker_instance_id,
                row.claim_fence,
            )
            == (
                claim.document_id,
                claim.run_id,
                claim.attempt_id,
                claim.worker_instance_id,
                claim.claim_fence,
            )
            and old.match(run, attempt, claim)
            and db.claim_metadata(run, attempt, claim)
            and run.status == "running"
            and run.fence == 1
        )
        if accepted and write:
            run.heartbeat_at = run.updated_at = now
            run.lease_expires_at = min(now + timedelta(seconds=15), run.deadline_at)
            if stage is not None and old.STAGES.index(stage) > old.STAGES.index(run.stage):
                run.stage = stage
        result = HeartbeatReceipt(accepted, state(run), run.heartbeat_at if accepted else None)
    return result


def heartbeat(runtime, claim, *, owner, stage=None):
    return _heartbeat(runtime, claim, owner, stage, True)


def read_heartbeat(runtime, claim, *, owner):
    return _heartbeat(runtime, claim, owner, None, False)


def snapshot_queued(engine):
    with db.transaction(engine) as session:
        session.execute(text("SELECT pg_advisory_xact_lock(1095911745,170301)"))
        rows = session.execute(
            select(Run.document_id, Run.id)
            .where(Run.status == "queued")
            .order_by(Run.created_at, Run.id)
            .limit(17)
        ).all()
        if len(rows) > 16:
            db.fail("queue_overflow")
        result = tuple(QueuedRun(*row) for row in rows)
    return result


def retire_queued(engine, item):
    if type(item) is not QueuedRun:
        db.fail("validation_error")
    db.uuid(item.document_id)
    db.uuid(item.run_id)
    with db.transaction(engine) as session:
        run, _, scope = locked(session, item.document_id, item.run_id)
        now = clock(session)
        old.expire(run, scope, now)
        if run.status == "queued":
            old.terminal(run, "failed", "interrupted", now)
        result = state(run)
    return result
