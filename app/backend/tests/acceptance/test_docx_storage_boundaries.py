"""Independent DOCX persistence boundaries, validation and safe corruption failures."""

import subprocess
import sys
import traceback
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from docx_package_fixtures import WORD_NS, build_package, minimal_parts
from docx_storage_fixtures import api, raw
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from ara.documents.storage import DocumentError, _not_found
from ara.docx_package import DocxError
from ara.docx_package.projection import ProjectionError

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "SYNTHETIC_DOCX_STORAGE_PRIVATE_6851"


def reject(operation, status, code, retryable=False):
    with pytest.raises(DocumentError) as caught:
        operation()
    error = caught.value
    assert (error.status, error.code, error.retryable) == (status, code, retryable)
    assert isinstance(error.message, str) and error.message
    assert str(error) == error.message
    rendered = "".join(traceback.format_exception(error))
    assert PRIVATE not in rendered + repr(error)
    if status == 404:
        assert error.message == _not_found().message
    elif status == 422:
        assert error.message == "Invalid request"
    elif status == 500:
        assert error.message == "Document storage operation failed"
    elif status == 503:
        assert error.message == "Document storage is unavailable"
    return error


def records(engine):
    with engine.connect() as connection:
        return tuple(
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT id, project_id, title, original_data, original_sha256, "
                    "current_data, current_sha256, storage_revision, "
                    "created_at::text AS created_at, updated_at::text AS updated_at "
                    "FROM docx_documents ORDER BY id"
                )
            ).mappings()
        )


def test_storage_imports_are_inert():
    code = """
import builtins, importlib, io, socket, subprocess
from pathlib import Path
import psycopg, sqlalchemy
import ara.config, ara.db, ara.models
names = ['ara.docx_documents'] + [
    '.'.join(p.with_suffix('').parts[1:])
    for p in sorted(Path('src/ara/docx_documents').rglob('*.py')) if p.name != '__init__.py'
]
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external I/O during DOCX storage import')
for target, name in (
    (builtins, 'open'), (io, 'open'), (Path, 'open'), (Path, 'read_text'),
    (Path, 'read_bytes'), (socket, 'socket'), (socket, 'create_connection'),
    (subprocess, 'Popen'), (subprocess, 'run'), (psycopg, 'connect'),
    (sqlalchemy, 'create_engine'), (ara.config, 'load_settings'),
    (ara.db, 'create_database_engine'),
):
    setattr(target, name, forbidden)
for name in names:
    importlib.import_module(name)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_scalar_validation_happens_before_database_access(run_world, monkeypatch):
    service = api()
    runtime = run_world["runtimes"]["own"]
    document_id, data = uuid4(), raw()

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid arguments must not open a database connection")

    monkeypatch.setattr(runtime.engine, "connect", forbidden)
    for bad in (None, str(document_id), document_id.hex, 0, True, b"uuid"):
        reject(lambda: service.get_docx(runtime, document_id=bad), 422, "validation_error")
        reject(
            lambda: service.import_docx(runtime, document_id=bad, title="Valid", data=data),
            422,
            "validation_error",
        )
        reject(
            lambda: service.save_docx(
                runtime, document_id=bad, expected_storage_revision=1, data=data
            ),
            422,
            "validation_error",
        )
    for bad in (None, 1, True, b"title", "", " \t\n", "a" * 201, "x\x00y", "\ud800"):
        reject(
            lambda: service.import_docx(runtime, document_id=document_id, title=bad, data=data),
            422,
            "validation_error",
        )
    for bad in (None, "bytes", bytearray(data), memoryview(data), 0):
        reject(
            lambda: service.import_docx(runtime, document_id=document_id, title="Valid", data=bad),
            422,
            "validation_error",
        )
        reject(
            lambda: service.save_docx(
                runtime, document_id=document_id, expected_storage_revision=1, data=bad
            ),
            422,
            "validation_error",
        )
    for bad in (None, True, False, 0, -1, 1.0, "1", 9223372036854775807):
        reject(
            lambda: service.save_docx(
                runtime, document_id=document_id, expected_storage_revision=bad, data=data
            ),
            422,
            "validation_error",
        )
    for field, values in (
        ("limit", (None, True, 0, -1, 101, 1.0, "1")),
        ("offset", (None, False, -1, 1.0, "0", 9223372036854775808)),
    ):
        for bad in values:
            reject(lambda: service.list_docx(runtime, **{field: bad}), 422, "validation_error")


def test_input_package_errors_keep_lower_layer_codes_before_database(run_world, monkeypatch):
    service = api()
    runtime, document_id = run_world["runtimes"]["own"], uuid4()
    parts = minimal_parts()
    parts["word/document.xml"] = (
        f'<w:document xmlns:w="{WORD_NS}"><w:body>'
        + "<w:customXml>" * 130
        + "</w:customXml>" * 130
        + "</w:body></w:document>"
    ).encode()
    cases = (
        (b"", DocxError, "invalid_package"),
        (PRIVATE.encode(), DocxError, "invalid_package"),
        (b"x" * (33554432 + 1), DocxError, "package_limit_exceeded"),
        (build_package(parts), ProjectionError, "projection_limit_exceeded"),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid packages must not open a database connection")

    monkeypatch.setattr(runtime.engine, "connect", forbidden)
    for data, error_type, code in cases:
        for operation in (
            lambda: service.import_docx(runtime, document_id=document_id, title="Valid", data=data),
            lambda: service.save_docx(
                runtime, document_id=document_id, expected_storage_revision=1, data=data
            ),
        ):
            with pytest.raises(error_type) as caught:
                operation()
            assert caught.value.code == code
            assert PRIVATE not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("part", ["original", "current"])
@pytest.mark.parametrize("damage", ["hash", "package"])
def test_both_stored_packages_are_checked_without_repair(run_world, part, damage):
    service, world = api(), run_world
    runtime, engine = world["runtimes"]["own"], world["engine"]
    document_id, data = uuid4(), raw()
    service.import_docx(runtime, document_id=document_id, title="Original", data=data)
    with engine.begin() as connection:
        if damage == "hash":
            connection.execute(
                text(f"UPDATE docx_documents SET {part}_sha256=:hash WHERE id=:id"),
                {"id": document_id, "hash": "0" * 64},
            )
        else:
            damaged = PRIVATE.encode()
            connection.execute(
                text(
                    f"UPDATE docx_documents SET {part}_data=:data, {part}_sha256=:hash WHERE id=:id"
                ),
                {"id": document_id, "data": damaged, "hash": sha256(damaged).hexdigest()},
            )
    before = records(engine)
    operations = (
        lambda target: service.get_docx(target, document_id=document_id),
        lambda target: service.save_docx(
            target, document_id=document_id, expected_storage_revision=777, data=data
        ),
        lambda target: service.import_docx(
            target, document_id=document_id, title="Different", data=data
        ),
    )
    for operation in operations:
        reject(lambda: operation(runtime), 500, "storage_error")
        for scope in ("peer", "foreign"):
            reject(lambda: operation(world["runtimes"][scope]), 404, "not_found")
    assert records(engine) == before


def test_malformed_stored_metadata_cannot_be_returned_or_overwritten(run_world):
    service, world = api(), run_world
    runtime, engine = world["runtimes"]["own"], world["engine"]
    document_id, data = uuid4(), raw()
    service.import_docx(runtime, document_id=document_id, title="Original", data=data)
    # Valid SQL values that cannot satisfy the public finite-datetime/title contract.
    for assignment in ("title = '   '", "updated_at = 'infinity'"):
        with engine.begin() as connection:
            connection.execute(
                text(f"UPDATE docx_documents SET {assignment} WHERE id=:id"), {"id": document_id}
            )
        before = records(engine)
        reject(lambda: service.get_docx(runtime, document_id=document_id), 500, "storage_error")
        reject(lambda: service.list_docx(runtime), 500, "storage_error")
        reject(
            lambda: service.save_docx(
                runtime, document_id=document_id, expected_storage_revision=1, data=data
            ),
            500,
            "storage_error",
        )
        assert records(engine) == before
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE docx_documents SET title='Original', updated_at=clock_timestamp() "
                    "WHERE id=:id"
                ),
                {"id": document_id},
            )


@pytest.mark.parametrize("operational", [False, True])
def test_sql_failures_are_safe_for_every_service_operation(run_world, operational):
    service, world = api(), run_world
    runtime, engine = world["runtimes"]["own"], world["engine"]
    document_id, data = uuid4(), raw()
    service.import_docx(runtime, document_id=document_id, title="Original", data=data)
    before = records(engine)

    def fail(*args):
        if operational:
            raise OperationalError(PRIVATE, {"secret": PRIVATE}, RuntimeError(PRIVATE))
        raise RuntimeError(PRIVATE)

    operations = (
        lambda: service.import_docx(runtime, document_id=uuid4(), title=PRIVATE, data=data),
        lambda: service.get_docx(runtime, document_id=document_id),
        lambda: service.list_docx(runtime),
        lambda: service.save_docx(
            runtime, document_id=document_id, expected_storage_revision=1, data=data
        ),
    )
    event.listen(engine, "before_cursor_execute", fail)
    try:
        for operation in operations:
            reject(
                operation,
                503 if operational else 500,
                "storage_unavailable" if operational else "storage_error",
                operational,
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert records(engine) == before
