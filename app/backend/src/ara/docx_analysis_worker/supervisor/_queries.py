"""Ordered read barriers and source-backed restoration; never resume old compute."""

from datetime import timedelta

from sqlalchemy import select, text

from ara.docx_analysis_runs import _lifecycle as life
from ara.docx_analysis_runs import _storage
from ara.docx_analysis_runs._lifecycle_models import WorkerClaim
from ara.docx_analysis_runs._lifecycle_storage import locked, state
from ara.models import DocxAnalysisAttempt as Attempt
from ara.models import DocxAnalysisResult as Result
from ara.models import DocxAnalysisRun as Run

from . import _sql as db
from . import lifecycle
from .sql_models import ClaimReceipt


def snapshot_active(engine):
    with db.transaction(engine) as session:
        session.execute(text("SELECT pg_advisory_xact_lock(1095911745,170301)"))
        rows = session.execute(
            select(Run.document_id, Run.id, Run.status)
            .where(Run.status.in_(("queued", "running", "cancel_requested")))
            .order_by(Run.created_at, Run.id)
            .limit(18)
        ).all()
        if (
            len(rows) > 17
            or sum(r.status == "queued" for r in rows) > 16
            or sum(r.status != "queued" for r in rows) > 1
        ):
            db.fail("recovery_required")
        return tuple(tuple(r) for r in rows)


def resolve_claim(runtime, *, document_id, run_id, attempt_id, worker_instance_id, owner):
    with db.transaction(runtime.engine) as session:
        run, attempt, _ = locked(session, document_id, run_id, runtime=runtime)
        if run.status != "running":
            return ClaimReceipt(None, state(run))
        if attempt is None or (attempt.id, attempt.worker_instance_id) != (
            attempt_id,
            worker_instance_id,
        ):
            db.fail("recovery_required")
    return lifecycle.claim_exact(
        runtime,
        document_id=document_id,
        run_id=run_id,
        attempt_id=attempt_id,
        worker_instance_id=worker_instance_id,
        owner=owner,
    )


def closed_publication(engine, claim, *, outcome, reply):
    with db.transaction(engine) as session:
        run, attempt, scope = locked(session, claim.document_id, claim.run_id)
        if (
            not life.match(run, attempt, claim)
            or not db.claim_metadata(run, attempt, claim)
            or scope != (run.accepted_project_id, run.accepted_owner_id)
        ):
            db.fail("recovery_required")
        result = session.scalar(select(Result).where(Result.run_id == run.id))
        status = run.status
        digest = run.result_sha256
        if outcome == "committed":
            if status != "succeeded" or result is None or result.reply_data != reply:
                db.fail("recovery_required")
        elif outcome in ("rolled_back", "terminal"):
            if status == "succeeded" or result is not None:
                db.fail("recovery_required")
            return state(run)
        else:
            db.fail("validation_error")
    restored = life.reconcile_attempt(engine, claim, expected_result_sha256=digest)
    if not restored.accepted:
        db.fail("recovery_required")
    return restored.state


def restore_closed(engine, binding):
    from ara.docx_analysis.storage_codec import AttemptBundle

    with db.transaction(engine) as session:
        run, attempt, scope = locked(session, binding.document_id, binding.run_id)
        if attempt is None or (attempt.id, attempt.worker_instance_id, attempt.claim_fence) != (
            binding.attempt_id,
            binding.worker_instance_id,
            1,
        ):
            db.fail("recovery_required")
        if scope != (run.accepted_project_id, run.accepted_owner_id):
            db.fail("recovery_required")
        result = state(run)
        if run.status != "succeeded":
            return result
        runtime = life.input_runtime(engine, run)
        started, deadline = run.started_at, run.deadline_at
        raw = session.scalar(select(Attempt.request_data).where(Attempt.id == attempt.id))
        bundle = AttemptBundle(attempt.id, raw, attempt.request_sha256)
        digest = run.result_sha256
    source = _storage.get_source(runtime, document_id=binding.document_id, run_id=binding.run_id)
    claim = WorkerClaim(
        binding.run_id,
        binding.document_id,
        binding.attempt_id,
        binding.worker_instance_id,
        1,
        source,
        bundle,
        started,
        deadline,
        min(started + timedelta(seconds=15), deadline),
    )
    out = life.reconcile_attempt(engine, claim, expected_result_sha256=digest)
    if not out.accepted:
        db.fail("recovery_required")
    return out.state
