"""Scoped transactions; no parsing or actor locks inside database transactions."""

from contextlib import contextmanager
from dataclasses import fields
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ara.documents.runtime import DocumentRuntime
from ara.docx_analysis.storage_codec import (
    SavedCheckCommand,
    SourceBundle,
    StorageCodecError,
    decode_command,
    restore_source,
)
from ara.docx_analysis.storage_codec._models import checked, uuid
from ara.models import DocxAnalysisRun as Run
from ara.models import DocxAnalysisSource as Source
from ara.models import DocxDocument, Project

from ._models import ACTIVE, TERMINAL, RunSummary, StartOutcome


def fail(code, status=500):
    from ara.documents.storage import DocumentError

    messages = {
        "validation_error": "Invalid request",
        "not_found": "Document or analysis run not found",
        "storage_error": "Analysis storage operation failed",
        "storage_unavailable": "Analysis storage is unavailable",
        "idempotency_conflict": "Analysis request does not match",
        "saved_target_conflict": "Saved analysis target does not match",
        "analysis_in_progress": "Document analysis is already active",
        "analysis_queue_full": "Analysis queue is full",
        "analysis_deadline_exceeded": "Analysis admission deadline has expired",
        "analysis_clock_error": "Analysis clock is unavailable",
        "analysis_history_exhausted": "Analysis history counter is exhausted",
        "unsupported_analysis_content": "Document content is not supported for analysis",
        "empty_document": "Document has no checkable text",
        "analysis_limit_exceeded": "Analysis exceeds a technical limit",
    }
    raise DocumentError(status, code, messages[code], status == 503)


def context(runtime):
    if (
        type(runtime) is not DocumentRuntime
        or not uuid(runtime.user_id)
        or not uuid(runtime.project_id)
    ):
        fail("validation_error", 422)
    try:
        runtime.__post_init__()
    except ValueError:
        fail("validation_error", 422)


@contextmanager
def transaction(runtime, *, admission=False):
    from ara.documents.storage import DocumentError

    try:
        with Session(runtime.engine) as session, session.begin():
            if admission:
                session.execute(text("SELECT pg_advisory_xact_lock(1095911745,170301)"))
            yield session
    except DocumentError:
        raise
    except OperationalError:
        fail("storage_unavailable", 503)
    except Exception:
        fail("storage_error")


def scope(session, runtime, document_id, *, writing=False):
    project = session.scalar(
        select(Project.id)
        .where(Project.id == runtime.project_id, Project.owner_id == runtime.user_id)
        .with_for_update(read=True)
    )
    if project is None:
        fail("not_found", 404)
    doc = session.scalar(
        select(DocxDocument.id)
        .where(DocxDocument.id == document_id, DocxDocument.project_id == runtime.project_id)
        .with_for_update(read=not writing)
    )
    if doc is None:
        fail("not_found", 404)


def clock(session):
    return session.scalar(select(func.clock_timestamp()))


def columns():
    return [
        Run.id.label("run_id") if f.name == "run_id" else getattr(Run, f.name)
        for f in fields(RunSummary)
    ]


def summary(row):
    return RunSummary(**{f.name: row[f.name] for f in fields(RunSummary)})


def replay(session, command, key, encoded):
    row = (
        session.execute(
            select(*columns(), Run.command_data, Run.command_sha256).where(
                Run.document_id == command.document_id, Run.client_request_id == key
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    # Validate even the small idempotency record before comparing caller intent.
    saved = decode_command(row["command_data"], expected_sha256=row["command_sha256"])
    result = summary(row)
    if saved.document_id != result.document_id:
        fail("storage_error")
    if type(saved) is SavedCheckCommand and (
        saved.storage_revision != result.storage_revision
        or saved.source_sha256 != result.source_sha256
    ):
        fail("storage_error")
    if encoded.data != row["command_data"] or encoded.sha256 != row["command_sha256"]:
        fail("idempotency_conflict", 409)
    return StartOutcome(result, True)


def lookup(runtime, command, key, encoded):
    with transaction(runtime) as session:
        scope(session, runtime, command.document_id)
        previous = replay(session, command, key, encoded)
        now = clock(session)
    return previous, now


def get_run(runtime, *, document_id, run_id):
    context(runtime)
    if not uuid(document_id) or not uuid(run_id):
        fail("validation_error", 422)
    with transaction(runtime) as session:
        scope(session, runtime, document_id)
        row = (
            session.execute(
                select(*columns()).where(Run.id == run_id, Run.document_id == document_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            fail("not_found", 404)
        result = summary(row)
    return result


def get_source(runtime, *, document_id, run_id, limits=None):
    context(runtime)
    if not uuid(document_id) or not uuid(run_id):
        fail("validation_error", 422)
    try:
        limits = checked(limits)
    except StorageCodecError:
        fail("validation_error", 422)
    with transaction(runtime) as session:
        scope(session, runtime, document_id)
        pair = session.execute(
            select(Run, Source)
            .join(
                Source,
                (Source.document_id == Run.document_id)
                & (Source.source_sha256 == Run.source_sha256),
            )
            .where(Run.id == run_id, Run.document_id == document_id)
        ).one_or_none()
        if pair is None:
            fail("not_found", 404)
        run, source = pair
        record = SourceBundle(
            **{
                f.name: source.source_data if f.name == "source_data" else getattr(run, f.name)
                for f in fields(SourceBundle)
            }
        )
    try:
        restore_source(record, limits=limits)
    except StorageCodecError as error:
        if error.code == "codec_limit_exceeded":
            fail("analysis_limit_exceeded", 413)
        fail("storage_error")
    return record


def timely(session, created):
    now = clock(session)
    if now < created:
        fail("analysis_clock_error", 503)
    if now >= created + timedelta(seconds=300):
        fail("analysis_deadline_exceeded", 408)
    return now


def enqueue(runtime, command, key, encoded, bundle, created, queue_limit):
    with transaction(runtime, admission=True) as session:
        scope(session, runtime, command.document_id, writing=True)
        previous = replay(session, command, key, encoded)
        if previous is not None:
            return previous
        admitted_at = timely(session, created)
        if session.scalar(
            select(Run.id)
            .where(Run.document_id == command.document_id, Run.status.in_(ACTIVE))
            .limit(1)
        ):
            fail("analysis_in_progress", 409)
        if (
            session.scalar(select(func.count()).select_from(Run).where(Run.status == "queued"))
            >= queue_limit
        ):
            fail("analysis_queue_full", 503)
        if hasattr(command, "retry_of_run_id"):
            parent = session.execute(
                select(Run.status, Run.storage_revision, Run.source_sha256).where(
                    Run.id == command.retry_of_run_id, Run.document_id == command.document_id
                )
            ).one_or_none()
            if parent is None:
                fail("not_found", 404)
            if parent.status not in TERMINAL:
                fail("analysis_in_progress", 409)
            if (parent.storage_revision, parent.source_sha256) != (
                bundle.storage_revision,
                bundle.source_sha256,
            ):
                fail("storage_error")
        order = (
            session.scalar(
                select(func.max(Run.accepted_order)).where(Run.document_id == command.document_id)
            )
            or 0
        )
        if order >= 2**63 - 1:
            fail("analysis_history_exhausted", 409)
        source = session.get(Source, (bundle.document_id, bundle.source_sha256))
        if source is None:
            session.add(
                Source(
                    document_id=bundle.document_id,
                    source_sha256=bundle.source_sha256,
                    source_data=bundle.source_data,
                )
            )
            session.flush()
        elif (
            source.source_data != bundle.source_data
            or sha256(source.source_data).hexdigest() != bundle.source_sha256
        ):
            fail("storage_error")
        run = Run(
            **{
                f.name: getattr(bundle, f.name)
                for f in fields(SourceBundle)
                if f.name != "source_data"
            },
            id=uuid4(),
            accepted_order=order + 1,
            accepted_project_id=runtime.project_id,
            accepted_owner_id=runtime.user_id,
            client_request_id=key,
            start_kind="saved" if type(command) is SavedCheckCommand else "retry",
            retry_of_run_id=getattr(command, "retry_of_run_id", None),
            status="queued",
            stage="queued",
            fence=0,
            attempt_id=None,
            result_sha256=None,
            error_code=None,
            created_at=created,
            deadline_at=created + timedelta(seconds=300),
            started_at=None,
            heartbeat_at=None,
            lease_expires_at=None,
            cancel_requested_at=None,
            finished_at=None,
            updated_at=admitted_at,
        )
        session.add(run)
        session.flush()
        timely(session, created)
        result = summary(
            {
                f.name: run.id if f.name == "run_id" else getattr(run, f.name)
                for f in fields(RunSummary)
            }
        )
    return StartOutcome(result, False)
