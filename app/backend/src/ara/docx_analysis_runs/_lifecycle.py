"""Fenced lifecycle only: no child process, model import or implicit scheduler."""

from dataclasses import fields
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, text

from ara.documents.runtime import DocumentRuntime
from ara.docx_analysis.storage_codec import (
    AttemptBundle,
    ResultBundle,
    SourceBundle,
    StorageCodecError,
    capture_result,
    prepare_attempt,
    restore_result,
)
from ara.docx_analysis.storage_codec._models import checked, digest, uuid
from ara.docx_analysis.storage_codec._records import LOWER_ERRORS
from ara.models import DocxAnalysisAttempt as Attempt
from ara.models import DocxAnalysisResult as Result
from ara.models import DocxAnalysisRun as Run
from ara.models import DocxDocument, Project

from . import _storage
from ._lifecycle_models import WorkerClaim, WorkerUpdate
from ._lifecycle_storage import locked, same_source, state, transaction
from ._models import TERMINAL

clock = _storage.clock
STAGES = ("preparing_document", "loading_model", "analyzing", "validating_result", "finishing")
FAIL_CODES = (
    "model_unavailable",
    "model_input_limit_exceeded",
    "invalid_result",
    "adapter_error",
    "analysis_limit_exceeded",
    "source_corrupt",
)


def valid_claim(claim):
    if type(claim) is not WorkerClaim:
        _storage.fail("validation_error", 422)
    if not all(
        uuid(getattr(claim, n, None))
        for n in ("run_id", "document_id", "attempt_id", "worker_instance_id")
    ):
        _storage.fail("validation_error", 422)
    if type(claim.claim_fence) is not int or claim.claim_fence != 1:
        _storage.fail("validation_error", 422)
    if type(claim.source) is not SourceBundle or type(claim.attempt) is not AttemptBundle:
        _storage.fail("validation_error", 422)
    if not all(
        type(t) is datetime and t.tzinfo is not None and t.utcoffset() is not None
        for t in (claim.claimed_at, claim.deadline_at, claim.lease_expires_at)
    ):
        _storage.fail("validation_error", 422)
    if not claim.claimed_at < claim.lease_expires_at <= claim.deadline_at:
        _storage.fail("validation_error", 422)


def limits_checked(limits):
    try:
        return checked(limits)
    except StorageCodecError:
        _storage.fail("validation_error", 422)


def match(run, attempt, claim):
    return (
        attempt is not None
        and run.attempt_id == claim.attempt_id
        and attempt.id == claim.attempt_id
        and (
            attempt.worker_instance_id == claim.worker_instance_id
            and attempt.claim_fence == claim.claim_fence
        )
    )


def terminal(run, status, code, now):
    run.status = run.stage = status
    run.error_code = code
    run.fence = 2 if run.attempt_id is not None else 1
    run.finished_at = run.updated_at = max(now, run.created_at)
    run.lease_expires_at = None
    if status == "cancelled" and run.cancel_requested_at is None:
        run.cancel_requested_at = max(now, run.created_at)


def expire(run, scope, now):
    if run.status in TERMINAL:
        return False
    if now >= run.deadline_at:
        terminal(run, "timed_out", "deadline_exceeded", now)
    elif scope != (run.accepted_project_id, run.accepted_owner_id):
        terminal(run, "failed", "ownership_changed", now)
    elif now < run.created_at or (run.heartbeat_at is not None and now < run.heartbeat_at):
        terminal(run, "failed", "interrupted", now)
    elif run.lease_expires_at is not None and now >= run.lease_expires_at:
        terminal(
            run,
            "cancelled" if run.status == "cancel_requested" else "failed",
            "cancelled" if run.status == "cancel_requested" else "interrupted",
            now,
        )
    else:
        return False
    return True


def input_runtime(engine, run):
    return DocumentRuntime(
        engine=engine,
        user_id=run.accepted_owner_id,
        project_id=run.accepted_project_id,
        mode="local",
    )


def claim_next(engine, *, worker_instance_id, limits=None):
    if not uuid(worker_instance_id):
        _storage.fail("validation_error", 422)
    limits = limits_checked(limits)
    with transaction(engine) as session:
        candidates = session.execute(
            select(Run.document_id, Run.id)
            .where(Run.status == "queued")
            .order_by(Run.created_at, Run.id)
            .limit(16)
        ).all()
    for document_id, run_id in candidates:
        with transaction(engine) as session:
            run, _, scope = locked(session, document_id, run_id)
            expire(run, scope, clock(session))
            if run.status != "queued":
                continue
            runtime = input_runtime(engine, run)
        try:
            source = _storage.get_source(
                runtime, document_id=document_id, run_id=run_id, limits=limits
            )
            prepared = prepare_attempt(source, attempt_id=uuid4(), limits=limits)
        except Exception as error:
            from ara.documents.storage import DocumentError

            if isinstance(error, DocumentError) and error.status == 503:
                raise
            if not isinstance(error, (DocumentError, StorageCodecError, *LOWER_ERRORS)):
                _storage.fail("storage_error")
            code = (
                "analysis_limit_exceeded"
                if getattr(error, "code", None)
                in ("analysis_limit_exceeded", "codec_limit_exceeded")
                else "source_corrupt"
            )
            with transaction(engine) as session:
                run, _, scope = locked(session, document_id, run_id)
                now = clock(session)
                expire(run, scope, now)
                if run.status == "queued":
                    terminal(run, "failed", code, now)
            continue
        with transaction(engine) as session:
            run, _, scope = locked(session, document_id, run_id)
            now = clock(session)
            expire(run, scope, now)
            if run.status != "queued":
                continue
            if not same_source(session, run, source):
                terminal(run, "failed", "source_corrupt", now)
                continue
            # Refresh the clock after bounded buffer reads, immediately before claim.
            now = clock(session)
            if expire(run, scope, now):
                continue
            lease = min(now + timedelta(seconds=15), run.deadline_at)
            session.add(
                Attempt(
                    id=prepared.attempt_id,
                    document_id=document_id,
                    run_id=run_id,
                    claim_fence=1,
                    worker_instance_id=worker_instance_id,
                    request_data=prepared.request_data,
                    request_sha256=prepared.request_sha256,
                    created_at=now,
                )
            )
            run.status = "running"
            run.stage = "preparing_document"
            run.fence = 1
            run.attempt_id = prepared.attempt_id
            run.started_at = run.heartbeat_at = run.updated_at = now
            run.lease_expires_at = lease
            session.flush()
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            result = WorkerClaim(
                run_id,
                document_id,
                prepared.attempt_id,
                worker_instance_id,
                1,
                source,
                prepared,
                now,
                run.deadline_at,
                lease,
            )
        return result
    return None


def heartbeat(engine, claim, *, stage=None):
    valid_claim(claim)
    if stage is not None and (type(stage) is not str or stage not in STAGES):
        _storage.fail("validation_error", 422)
    with transaction(engine) as session:
        run, attempt, scope = locked(session, claim.document_id, claim.run_id)
        if not match(run, attempt, claim):
            return WorkerUpdate(False, state(run))
        now = clock(session)
        expire(run, scope, now)
        if run.status != "running" or run.fence != 1:
            return WorkerUpdate(False, state(run))
        run.heartbeat_at = run.updated_at = now
        run.lease_expires_at = min(now + timedelta(seconds=15), run.deadline_at)
        if stage is not None and STAGES.index(stage) > STAGES.index(run.stage):
            run.stage = stage
        result = WorkerUpdate(True, state(run))
    return result


def _scoped(runtime, document_id, run_id, cancel):
    _storage.context(runtime)
    if not uuid(document_id) or not uuid(run_id):
        _storage.fail("validation_error", 422)
    with transaction(runtime.engine) as session:
        run, _, scope = locked(session, document_id, run_id, runtime=runtime)
        now = clock(session)
        expire(run, scope, now)
        if cancel and run.status == "queued":
            terminal(run, "cancelled", "cancelled", now)
        elif cancel and run.status == "running":
            run.status = run.stage = "cancel_requested"
            run.fence = 2
            run.cancel_requested_at = run.updated_at = now
        result = state(run)
    return result


def cancel_run(runtime, *, document_id, run_id):
    return _scoped(runtime, document_id, run_id, True)


def read_state(runtime, *, document_id, run_id):
    return _scoped(runtime, document_id, run_id, False)


def acknowledge_cancel(engine, claim):
    valid_claim(claim)
    with transaction(engine) as session:
        run, attempt, scope = locked(session, claim.document_id, claim.run_id)
        if not match(run, attempt, claim):
            return WorkerUpdate(False, state(run))
        now = clock(session)
        expire(run, scope, now)
        accepted = run.status == "cancel_requested"
        if accepted:
            terminal(run, "cancelled", "cancelled", now)
        result = WorkerUpdate(accepted, state(run))
    return result


def fail_attempt(engine, claim, *, error_code):
    valid_claim(claim)
    if type(error_code) is not str or error_code not in FAIL_CODES:
        _storage.fail("validation_error", 422)
    with transaction(engine) as session:
        run, attempt, scope = locked(session, claim.document_id, claim.run_id)
        if not match(run, attempt, claim):
            return WorkerUpdate(False, state(run))
        now = clock(session)
        expire(run, scope, now)
        accepted = run.status == "running" and run.fence == 1
        if accepted:
            terminal(run, "failed", error_code, now)
        result = WorkerUpdate(accepted, state(run))
    return result


def load_records(engine, claim, limits):
    # Copy DB records under ordered locks; validation happens after release.
    with transaction(engine) as session:
        run, attempt, scope = locked(session, claim.document_id, claim.run_id)
        if not match(run, attempt, claim):
            return None, WorkerUpdate(False, state(run))
        expire(run, scope, clock(session))
        if run.status not in ("running", "succeeded"):
            return None, WorkerUpdate(False, state(run))
        runtime = input_runtime(engine, run)
        raw = session.scalar(select(Attempt.request_data).where(Attempt.id == attempt.id))
        bundle = AttemptBundle(attempt.id, raw, attempt.request_sha256)
        prior = None
        if run.status == "succeeded":
            value = session.scalar(select(Result).where(Result.run_id == run.id))
            if value is None or value.result_sha256 != run.result_sha256:
                _storage.fail("storage_error")
            prior = ResultBundle(**{f.name: getattr(value, f.name) for f in fields(ResultBundle)})
    source = _storage.get_source(
        runtime, document_id=claim.document_id, run_id=claim.run_id, limits=limits
    )
    return (source, bundle, prior), None


def _replay(engine, claim, source, attempt, result, limits, expected=None, reply=None):
    try:
        envelope = restore_result(source, attempt, result, limits=limits)
    except (*LOWER_ERRORS, StorageCodecError):
        _storage.fail("storage_error")
    with transaction(engine) as session:
        run, a, scope = locked(session, claim.document_id, claim.run_id)
        good = (
            match(run, a, claim)
            and run.status == "succeeded"
            and run.result_sha256 == envelope.result_sha256
        )
        if good:
            good = (
                same_source(session, run, source)
                and session.scalar(select(Attempt.request_data).where(Attempt.id == a.id))
                == attempt.request_data
            )
        if not good:
            _storage.fail("storage_error")
        accepted = (expected is None or expected == envelope.result_sha256) and (
            reply is None or reply == result.reply_data
        )
        outcome = WorkerUpdate(accepted, state(run), accepted)
    return outcome


def complete_attempt(engine, claim, *, reply, limits=None):
    from ara.documents.storage import DocumentError

    valid_claim(claim)
    limits = limits_checked(limits)
    if type(reply) is not bytes:
        _storage.fail("validation_error", 422)
    try:
        records, denied = load_records(engine, claim, limits)
        if denied is not None:
            return denied
        source, attempt, prior = records
    except DocumentError as error:
        if error.status == 503:
            raise
        with transaction(engine) as session:
            run, _, _ = locked(session, claim.document_id, claim.run_id)
            if run.status == "succeeded":
                raise error
        code = (
            "analysis_limit_exceeded"
            if error.code == "analysis_limit_exceeded"
            else "source_corrupt"
        )
        denied = fail_attempt(engine, claim, error_code=code)
        return WorkerUpdate(False, denied.state)
    if prior is not None:
        return _replay(engine, claim, source, attempt, prior, limits, reply=reply)
    try:
        result = capture_result(source, attempt, reply=reply, limits=limits)
    except (*LOWER_ERRORS, StorageCodecError) as error:
        code = "analysis_limit_exceeded" if "limit" in error.code else "invalid_result"
        out = fail_attempt(engine, claim, error_code=code)
        return WorkerUpdate(False, out.state)
    with transaction(engine) as session:
        run, a, scope = locked(session, claim.document_id, claim.run_id)
        if not match(run, a, claim):
            return WorkerUpdate(False, state(run))
        now = clock(session)
        expire(run, scope, now)
        if run.status == "succeeded":
            # Another identical completion may have won while validation ran.
            stored = session.scalar(select(Result).where(Result.run_id == run.id))
            if stored is not None and stored.reply_data != reply:
                return WorkerUpdate(False, state(run))
            intact = (
                stored is not None
                and run.result_sha256 == result.result_sha256
                and all(
                    getattr(stored, f.name) == getattr(result, f.name) for f in fields(ResultBundle)
                )
                and same_source(session, run, source)
                and a.request_sha256 == attempt.request_sha256
                and session.scalar(select(Attempt.request_data).where(Attempt.id == a.id))
                == attempt.request_data
            )
            if not intact:
                _storage.fail("storage_error")
            accepted = True
            return WorkerUpdate(accepted, state(run), accepted)
        if run.status != "running" or run.fence != 1:
            return WorkerUpdate(False, state(run))
        if (
            not same_source(session, run, source)
            or a.request_sha256 != attempt.request_sha256
            or (
                session.scalar(select(Attempt.request_data).where(Attempt.id == a.id))
                != attempt.request_data
            )
        ):
            terminal(run, "failed", "source_corrupt", now)
            return WorkerUpdate(False, state(run))
        now = clock(session)
        if expire(run, scope, now):
            return WorkerUpdate(False, state(run))
        session.add(
            Result(
                run_id=run.id,
                document_id=run.document_id,
                attempt_id=a.id,
                run_status="succeeded",
                created_at=now,
                **{f.name: getattr(result, f.name) for f in fields(ResultBundle)},
            )
        )
        terminal(run, "succeeded", None, now)
        run.result_sha256 = result.result_sha256
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        outcome = WorkerUpdate(True, state(run))
    return outcome


def reconcile_attempt(engine, claim, *, expected_result_sha256, limits=None):
    valid_claim(claim)
    limits = limits_checked(limits)
    if not digest(expected_result_sha256):
        _storage.fail("validation_error", 422)
    records, denied = load_records(engine, claim, limits)
    if denied is not None:
        return denied
    source, attempt, prior = records
    if prior is None:
        with transaction(engine) as session:
            run, _, _ = locked(session, claim.document_id, claim.run_id)
            return WorkerUpdate(False, state(run))
    return _replay(engine, claim, source, attempt, prior, limits, expected=expected_result_sha256)


def reap_expired(engine, *, limit=32):
    if type(limit) is not int or not 1 <= limit <= 128:
        _storage.fail("validation_error", 422)
    with transaction(engine) as session:
        now = clock(session)
        candidates = session.execute(
            select(Run.document_id, Run.id)
            .join(DocxDocument, DocxDocument.id == Run.document_id)
            .join(Project, Project.id == DocxDocument.project_id)
            .where(
                Run.status.in_(("queued", "running", "cancel_requested")),
                or_(
                    Run.deadline_at <= now,
                    Run.lease_expires_at <= now,
                    Run.created_at > now,
                    Run.heartbeat_at > now,
                    DocxDocument.project_id != Run.accepted_project_id,
                    Project.owner_id != Run.accepted_owner_id,
                ),
            )
            .order_by(Run.deadline_at, Run.id)
            .limit(limit)
        ).all()
    results = []
    for document_id, run_id in candidates:
        with transaction(engine) as session:
            run, _, scope = locked(session, document_id, run_id)
            changed = expire(run, scope, clock(session))
            if changed:
                results.append(state(run))
    return tuple(results)
