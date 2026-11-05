"""Trusted SQL recording layer; physical proof belongs to the owning supervisor."""

from sqlalchemy import select, text

from ara.docx_analysis_runs import _lifecycle as life
from ara.docx_analysis_runs import _storage
from ara.docx_analysis_runs._lifecycle_storage import locked as lock_run
from ara.models import DocxAnalysisAttempt as Attempt
from ara.models import DocxAnalysisResult as Result
from ara.models import DocxAnalysisRun as Run
from ara.models import DocxAnalysisSource as Source

from . import _sql as db


def read_fence(engine):
    with db.transaction(engine) as session:
        result = db.view(db.locked(session))
    return result


def provision_new_database(engine, *, installation_id, expected_revision):
    db.uuid(installation_id)
    db.revision(expected_revision)
    values = dict(phase="clean", installation_id=installation_id, owner_epoch=None)
    with db.transaction(engine) as session:
        session.execute(text("SELECT pg_advisory_xact_lock(1095911745,170301)"))
        row = db.locked(session)
        if db.replay(row, expected_revision, values):
            result = db.view(row)
        else:
            if row.phase != "unprovisioned":
                db.fail()
            if any(
                session.scalar(select(table).limit(1)) is not None
                for table in (Run.id, Attempt.id, Result.run_id, Source.document_id)
            ):
                db.fail("recovery_required")
            result = db.update(row, expected_revision, values)
    return result


def take_ownership(engine, *, owner, expected_revision):
    db.owner(owner)
    db.revision(expected_revision)
    with db.transaction(engine) as session:
        row = db.locked(session)
        if row.phase not in ("clean", "drained"):
            db.fail("recovery_required")
        if row.installation_id != owner.installation_id:
            db.fail()
        values = dict(owner_epoch=owner.owner_epoch)
        result = (
            db.view(row)
            if db.replay(row, expected_revision, values)
            else db.update(row, expected_revision, values)
        )
    return result


def arm_launch(runtime, claim, *, binding, expected_revision):
    _storage.context(runtime)
    life.valid_claim(claim)
    db.binding(binding)
    db.revision(expected_revision)
    if (
        binding.document_id,
        binding.run_id,
        binding.attempt_id,
        binding.worker_instance_id,
        binding.claim_fence,
    ) != (
        claim.document_id,
        claim.run_id,
        claim.attempt_id,
        claim.worker_instance_id,
        claim.claim_fence,
    ):
        db.fail("validation_error")
    with db.transaction(runtime.engine) as session:
        run, attempt, scope = lock_run(session, claim.document_id, claim.run_id, runtime=runtime)
        row = db.locked(session)
        values = dict(phase="armed", **db.desired_binding(binding))
        db.owned(row, binding.owner)
        if db.replay(row, expected_revision, values):
            result = db.view(row)
        else:
            life.expire(run, scope, life.clock(session))
            if row.phase != "clean" or run.status != "running" or run.fence != 1:
                db.fail()
            if not life.match(run, attempt, claim) or not db.claim_metadata(run, attempt, claim):
                db.fail()
            result = db.update(row, expected_revision, values)
    return result


def record_drained(engine, *, binding, expected_revision):
    db.binding(binding)
    db.revision(expected_revision)
    with db.transaction(engine) as session:
        row = db.locked(session)
        db.bound(row, binding)
        values = dict(phase="drained")
        if db.replay(row, expected_revision, values):
            result = db.view(row)
        else:
            if row.phase != "armed":
                db.fail()
            result = db.update(row, expected_revision, values)
    return result


def clear_drained(engine, *, binding, expected_revision):
    db.binding(binding)
    db.revision(expected_revision)
    values = dict(phase="clean", **{field: None for field in db.FIELDS})
    # A completed clear needs no run lock: the old row may already be deleted.
    # Finish this read-only barrier transaction before taking any run locks.
    with db.transaction(engine) as session:
        row = db.locked(session)
        db.owned(row, binding.owner)
        if db.replay(row, expected_revision, values):
            return db.view(row)
    with db.transaction(engine) as session:
        run, attempt, scope = lock_run(session, binding.document_id, binding.run_id)
        row = db.locked(session)
        db.bound(row, binding)
        if row.phase != "drained":
            db.fail()
        life.expire(run, scope, life.clock(session))
        if (
            attempt is None
            or attempt.id != binding.attempt_id
            or attempt.worker_instance_id != binding.worker_instance_id
            or attempt.claim_fence != binding.claim_fence
            or run.status not in life.TERMINAL
        ):
            db.fail()
        if run.status == "succeeded":
            result = session.scalar(select(Result).where(Result.run_id == run.id))
            if result is None or (result.document_id, result.attempt_id, result.result_sha256) != (
                run.document_id,
                attempt.id,
                run.result_sha256,
            ):
                db.fail("storage_error")
        result = db.update(row, expected_revision, values)
    return result
