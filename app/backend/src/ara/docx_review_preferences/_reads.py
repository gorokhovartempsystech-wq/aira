"""Scoped finite SQL transactions and detached immutable origin records."""

from contextlib import contextmanager
from dataclasses import fields
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, OperationalError, TimeoutError
from sqlalchemy.orm import Session

from ara.documents.runtime import DocumentRuntime
from ara.documents.storage import DocumentError
from ara.docx_analysis.storage_codec import AttemptBundle, ResultBundle, SourceBundle
from ara.docx_analysis_runs import _storage
from ara.models import DocxAnalysisAttempt as Attempt
from ara.models import DocxAnalysisResult as Result
from ara.models import DocxAnalysisRun as Run
from ara.models import DocxAnalysisSource as Source
from ara.models import DocxReviewDismissal as Dismissal
from ara.models import DocxReviewPreferences as Preferences
from ara.models import DocxReviewReceipt as Receipt

from . import _codec
from ._models import MAX_HIDDEN, Origin, PreferencesState, fail, require


def context(runtime, document_id):
    require(type(runtime) is DocumentRuntime and type(document_id) is UUID)
    require(type(runtime.user_id) is UUID and type(runtime.project_id) is UUID)
    require(runtime.mode == "local" and runtime.engine.dialect.name == "postgresql")


@contextmanager
def transaction(runtime, document_id, *, writing=False):
    context(runtime, document_id)
    try:
        with Session(runtime.engine) as session, session.begin():
            for statement in (
                "SET LOCAL lock_timeout='500ms'",
                "SET LOCAL statement_timeout='2s'",
                "SET LOCAL idle_in_transaction_session_timeout='2s'",
                "SET LOCAL transaction_timeout='5s'",
            ):
                session.execute(text(statement))
            if session.scalar(text("SELECT version_num FROM alembic_version")) not in (
                "0013_docx_review_preferences",
                "0014_docx_file_states",
            ):
                fail("preferences_schema_unavailable")
            _storage.scope(session, runtime, document_id, writing=writing)
            yield session
    except DocumentError:
        raise
    except (OperationalError, TimeoutError):
        fail("storage_unavailable")
    except DBAPIError as error:
        fail("storage_unavailable" if error.connection_invalidated else "storage_error")
    except Exception:
        fail("storage_error")


def snapshot(session, document_id):
    row = session.get(Preferences, document_id)
    if row is None:
        return PreferencesState(document_id, 0, (), True, False, ())
    try:
        values = _codec.preferences(row.disabled_types, row.show_questions, row.show_hidden)
        require(tuple(row.disabled_types) == values["disabled_types"])
        require(_codec.counter(row.revision) and row.revision > 0)
        items = session.execute(
            select(Dismissal.dismissal_key, Dismissal.hidden_at_revision)
            .where(Dismissal.document_id == document_id)
            .order_by(Dismissal.dismissal_key)
            .limit(MAX_HIDDEN + 1)
        ).all()
        require(len(items) <= MAX_HIDDEN)
        require(
            all(
                _codec.digest(key, "dh-")
                and _codec.counter(revision)
                and 1 <= revision <= row.revision
                for key, revision in items
            )
        )
    except DocumentError:
        fail("storage_error")
    return PreferencesState(
        document_id, row.revision, **values, hidden_keys=tuple(key for key, _ in items)
    )


def get_state(runtime, *, document_id):
    with transaction(runtime, document_id) as session:
        return snapshot(session, document_id)


def replay(session, command):
    row = session.get(Receipt, (command.document_id, command.command_id))
    if row is None:
        return None
    parent = session.get(Preferences, command.document_id)
    require(
        parent is not None
        and _codec.counter(parent.revision)
        and 1 <= row.revision <= parent.revision,
        "storage_error",
    )
    return _codec.read_receipt(row, command)


def records(session, document_id, run_id, result_sha256):
    run = session.scalar(select(Run).where(Run.id == run_id, Run.document_id == document_id))
    if run is None:
        fail("not_found")
    if run.status != "succeeded":
        fail("result_not_ready")
    source = session.get(Source, (document_id, run.source_sha256))
    attempt = session.get(Attempt, run.attempt_id)
    result = session.get(Result, run.id)
    require(source is not None and attempt is not None and result is not None, "storage_error")
    require((attempt.document_id, attempt.run_id) == (document_id, run.id), "storage_error")
    require(
        (result.document_id, result.attempt_id, result.result_sha256)
        == (document_id, attempt.id, run.result_sha256),
        "storage_error",
    )
    if result.result_sha256 != result_sha256:
        fail("preferences_conflict")
    return Origin(
        run.id,
        SourceBundle(
            **{
                f.name: source.source_data if f.name == "source_data" else getattr(run, f.name)
                for f in fields(SourceBundle)
            }
        ),
        AttemptBundle(attempt.id, attempt.request_data, attempt.request_sha256),
        ResultBundle(**{f.name: getattr(result, f.name) for f in fields(ResultBundle)}),
    )
