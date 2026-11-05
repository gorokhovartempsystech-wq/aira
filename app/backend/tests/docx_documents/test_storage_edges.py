"""Additional DOCX storage boundaries using only synthetic, disposable data."""

import traceback
from hashlib import sha256
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile, ZipInfo

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError

from ara.documents.runtime import DocumentRuntime
from ara.documents.storage import DocumentError
from ara.docx_package.projection import ProjectionError, ProjectionLimits
from ara.docx_package.session import DocxSession
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine

PRIVATE = "SYNTHETIC_DOCX_STORAGE_EDGE_PRIVATE"


def _document(*, nesting=0):
    parts = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/main.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.document.main+xml"/></Types>'
        ),
        "_rels/.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="main" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="main.xml"/></Relationships>'
        ),
        "main.xml": (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body>'
            + "<w:customXml>" * nesting
            + "<w:p><w:r><w:t>Synthetic text</w:t></w:r></w:p>"
            + "</w:customXml>" * nesting
            + "</w:body></w:document>"
        ),
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, value in parts.items():
            archive.writestr(ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), value.encode())
    return buffer.getvalue()


@pytest.fixture
def runtime(pg_engine):
    owner, project = uuid4(), uuid4()
    with pg_engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner})
        connection.execute(
            text("INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, 'Synthetic')"),
            {"id": project, "owner": owner},
        )
    return DocumentRuntime(engine=pg_engine, user_id=owner, project_id=project, mode="local")


@pytest.fixture
def no_connection_runtime(monkeypatch):
    # Constructing an engine is inert; every attempted connection is a test failure.
    engine = create_engine("postgresql+psycopg://", hide_parameters=True)

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid input must be rejected before database access")

    monkeypatch.setattr(engine, "connect", forbidden)
    yield DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
    engine.dispose()


def _reject(operation, *, operational=False, code=None):
    with pytest.raises(DocumentError) as caught:
        operation()
    error = caught.value
    status = 422 if code == "validation_error" else 503 if operational else 500
    expected_code = code or ("storage_unavailable" if operational else "storage_error")
    assert (error.status, error.code, error.retryable) == (status, expected_code, operational)
    expected_message = (
        "Invalid request"
        if status == 422
        else "Document storage is unavailable"
        if status == 503
        else "Document storage operation failed"
    )
    assert error.message == str(error) == expected_message
    assert PRIVATE not in "".join(traceback.format_exception(error)) + repr(error)
    assert error.__cause__ is None
    assert error.__suppress_context__ or error.__context__ is None


def _rows(engine):
    with engine.connect() as connection:
        return connection.execute(text("SELECT * FROM docx_documents ORDER BY id")).all()


def _import(runtime):
    from ara.docx_documents import import_docx

    return import_docx(runtime, document_id=uuid4(), title="Synthetic", data=_document())


def _operations(runtime, stored):
    from ara.docx_documents import get_docx, import_docx, list_docx, save_docx

    return {
        "get": lambda: get_docx(runtime, document_id=stored.document_id),
        "list": lambda: list_docx(runtime),
        "replay": lambda: import_docx(
            runtime, document_id=stored.document_id, title=stored.title, data=stored.original_data
        ),
        "save": lambda: save_docx(
            runtime,
            document_id=stored.document_id,
            expected_storage_revision=stored.storage_revision,
            data=stored.current_data,
        ),
    }


@pytest.mark.parametrize("operation", ["get", "list", "replay"])
@pytest.mark.parametrize("operational", [False, True])
def test_read_and_replay_commit_failure_never_returns_prepared_snapshot(
    runtime, operation, operational
):
    stored = _import(runtime)
    before = _rows(runtime.engine)

    def fail_commit(connection):
        if operational:
            raise OperationalError(PRIVATE, {"title": PRIVATE}, RuntimeError(PRIVATE))
        raise RuntimeError(PRIVATE)

    event.listen(runtime.engine, "commit", fail_commit)
    try:
        _reject(_operations(runtime, stored)[operation], operational=operational)
    finally:
        event.remove(runtime.engine, "commit", fail_commit)
    assert _rows(runtime.engine) == before
    assert _operations(runtime, stored)["get"]() == stored


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_at", None),
        ("updated_at", None),
        ("storage_revision", 0),
        ("current_sha256", "UPPERCASE_AND_TOO_SHORT"),
    ],
)
def test_missing_or_malformed_metadata_fails_before_replay_or_save(runtime, field, value):
    stored = _import(runtime)
    with runtime.engine.begin() as connection:
        if value is None:
            connection.execute(
                text(f"ALTER TABLE docx_documents ALTER COLUMN {field} DROP NOT NULL")
            )
        else:
            checks = inspect(connection).get_check_constraints("docx_documents")
            matching = [check for check in checks if field in check["sqltext"]]
            assert len(matching) == 1
            name = connection.dialect.identifier_preparer.quote(matching[0]["name"])
            connection.execute(text(f"ALTER TABLE docx_documents DROP CONSTRAINT {name}"))
        connection.execute(
            text(f"UPDATE docx_documents SET {field}=:value WHERE id=:id"),
            {"value": value, "id": stored.document_id},
        )
    before = _rows(runtime.engine)
    for operation in _operations(runtime, stored).values():
        _reject(operation)
        assert _rows(runtime.engine) == before


def test_metadata_listing_does_not_validate_or_repair_stored_package(runtime):
    from ara.docx_documents import get_docx, list_docx

    stored = _import(runtime)
    damaged = PRIVATE.encode()
    with runtime.engine.begin() as connection:
        connection.execute(
            text("UPDATE docx_documents SET current_data=:data, current_sha256=:hash WHERE id=:id"),
            {"id": stored.document_id, "data": damaged, "hash": sha256(damaged).hexdigest()},
        )
    before = _rows(runtime.engine)
    (summary,) = list_docx(runtime)
    assert summary.document_id == stored.document_id
    assert summary.current_size_bytes == len(damaged)
    assert summary.current_sha256 == sha256(damaged).hexdigest()
    _reject(lambda: get_docx(runtime, document_id=stored.document_id))
    assert _rows(runtime.engine) == before


@pytest.mark.parametrize("part", ["original", "current"])
def test_stored_valid_hash_cannot_hide_projection_limit_corruption(runtime, part):
    stored = _import(runtime)
    excessive = _document(nesting=130)
    relaxed = DocxSession(excessive, projection_limits=ProjectionLimits(max_depth=256))
    assert relaxed.snapshot().data == excessive
    with runtime.engine.begin() as connection:
        connection.execute(
            text(f"UPDATE docx_documents SET {part}_data=:data, {part}_sha256=:hash WHERE id=:id"),
            {"id": stored.document_id, "data": excessive, "hash": sha256(excessive).hexdigest()},
        )
    before = _rows(runtime.engine)
    operations = _operations(runtime, stored)
    for name in ("get", "replay", "save"):
        _reject(operations[name])
    assert _rows(runtime.engine) == before


def test_relaxed_session_limits_do_not_expand_storage_input_limits(no_connection_runtime):
    from ara.docx_documents import import_docx, save_docx

    excessive = _document(nesting=130)
    snapshot = DocxSession(excessive, projection_limits=ProjectionLimits(max_depth=256)).snapshot()
    for operation in (
        lambda: import_docx(
            no_connection_runtime, document_id=uuid4(), title="Synthetic", data=snapshot.data
        ),
        lambda: save_docx(
            no_connection_runtime,
            document_id=uuid4(),
            expected_storage_revision=1,
            data=snapshot.data,
        ),
    ):
        with pytest.raises(ProjectionError) as caught:
            operation()
        assert caught.value.code == "projection_limit_exceeded"


def test_scalar_subclasses_are_rejected_before_database_access(no_connection_runtime):
    from ara.docx_documents import import_docx, list_docx, save_docx

    class String(str):
        pass

    class Binary(bytes):
        pass

    class Number(int):
        pass

    runtime, document_id, data = no_connection_runtime, uuid4(), _document()
    for operation in (
        lambda: import_docx(runtime, document_id=document_id, title=String("Title"), data=data),
        lambda: import_docx(runtime, document_id=document_id, title="Title", data=Binary(data)),
        lambda: save_docx(
            runtime, document_id=document_id, expected_storage_revision=1, data=Binary(data)
        ),
        lambda: save_docx(
            runtime, document_id=document_id, expected_storage_revision=Number(1), data=data
        ),
        lambda: list_docx(runtime, limit=Number(1)),
        lambda: list_docx(runtime, offset=Number(0)),
    ):
        _reject(operation, code="validation_error")


def test_lost_import_commit_ack_replays_one_identity_and_keeps_later_draft(runtime, monkeypatch):
    from ara.docx_documents import get_docx, import_docx, save_docx

    document_id, data = uuid4(), _document()
    real_commit = runtime.engine.dialect.do_commit

    def commit_without_ack(connection):
        real_commit(connection)
        raise OperationalError(PRIVATE, {}, RuntimeError(PRIVATE))

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", commit_without_ack)
        _reject(
            lambda: import_docx(runtime, document_id=document_id, title="Synthetic", data=data),
            operational=True,
        )
    recovered = get_docx(runtime, document_id=document_id)
    assert recovered.storage_revision == 1
    assert import_docx(runtime, document_id=document_id, title="Synthetic", data=data) == recovered
    changed = save_docx(
        runtime, document_id=document_id, expected_storage_revision=1, data=_document(nesting=1)
    )
    assert changed.storage_revision == 2 and changed.current_data != data
    assert import_docx(runtime, document_id=document_id, title="Synthetic", data=data) == changed
    assert len(_rows(runtime.engine)) == 1
