"""Metadata-only row locks in project/document/run/attempt order."""

from contextlib import contextmanager
from dataclasses import fields

from sqlalchemy import Engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, load_only

from ara.models import DocxAnalysisAttempt as Attempt
from ara.models import DocxAnalysisRun as Run
from ara.models import DocxAnalysisSource as Source
from ara.models import DocxDocument, Project

from . import _storage
from ._lifecycle_models import RunState
from ._models import RunSummary

RUN_BUFFERS = ("command_data", "snapshot_data", "execution_spec")


@contextmanager
def transaction(engine):
    from ara.documents.storage import DocumentError

    if not isinstance(engine, Engine):
        _storage.fail("validation_error", 422)
    try:
        with Session(engine) as session, session.begin():
            yield session
    except DocumentError:
        raise
    except OperationalError:
        _storage.fail("storage_unavailable", 503)
    except Exception:
        _storage.fail("storage_error")


def locked(session, document_id, run_id, *, runtime=None):
    if runtime is not None:
        _storage.scope(session, runtime, document_id, writing=True)
        owner, pid = runtime.user_id, runtime.project_id
    else:
        pid = session.scalar(select(DocxDocument.project_id).where(DocxDocument.id == document_id))
        owner = session.scalar(
            select(Project.owner_id).where(Project.id == pid).with_for_update(read=True)
        )
        doc = session.execute(
            select(DocxDocument.id, DocxDocument.project_id)
            .where(DocxDocument.id == document_id)
            .with_for_update()
        ).one_or_none()
        if doc is None or owner is None:
            _storage.fail("not_found", 404)
        # A concurrent move never licenses a write while holding the wrong project lock.
        if doc.project_id != pid:
            _storage.fail("storage_unavailable", 503)
    attrs = [getattr(Run, c.name) for c in Run.__table__.columns if c.name not in RUN_BUFFERS]
    run = session.scalar(
        select(Run)
        .options(load_only(*attrs, raiseload=True))
        .where(Run.id == run_id, Run.document_id == document_id)
        .with_for_update()
    )
    if run is None:
        _storage.fail("not_found", 404)
    attempt = None
    if run.attempt_id is not None:
        attrs = [
            getattr(Attempt, c.name) for c in Attempt.__table__.columns if c.name != "request_data"
        ]
        attempt = session.scalar(
            select(Attempt)
            .options(load_only(*attrs, raiseload=True))
            .where(
                Attempt.id == run.attempt_id,
                Attempt.run_id == run.id,
                Attempt.document_id == document_id,
            )
            .with_for_update()
        )
        if attempt is None:
            _storage.fail("storage_error")
    return run, attempt, (pid, owner)


def state(run):
    result = _storage.summary(
        {f.name: run.id if f.name == "run_id" else getattr(run, f.name) for f in fields(RunSummary)}
    )
    return RunState(
        result,
        run.attempt_id,
        run.fence,
        run.error_code,
        run.lease_expires_at,
        run.cancel_requested_at,
    )


def same_source(session, run, source):
    buffers = session.execute(
        select(*(getattr(Run, n) for n in RUN_BUFFERS)).where(Run.id == run.id)
    ).one()
    data = dict(zip(RUN_BUFFERS, buffers, strict=True))
    for f in fields(source):
        if f.name == "source_data":
            continue
        if (data[f.name] if f.name in data else getattr(run, f.name)) != getattr(source, f.name):
            return False
    raw = session.scalar(
        select(Source.source_data).where(
            Source.document_id == run.document_id, Source.source_sha256 == run.source_sha256
        )
    )
    return raw == source.source_data
