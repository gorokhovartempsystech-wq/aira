"""Independent D02-06 persistence acceptance on disposable PostgreSQL databases."""

import base64
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from docx_editing_fixtures import MAIN, text_spans, zip_parts
from docx_projection_fixtures import package, paragraph
from docx_storage_fixtures import api, raw
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool
from test_docx_ranges import change

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/docx/rich-source.docx"
STORED_FIELDS = {
    "document_id",
    "title",
    "original_data",
    "original_sha256",
    "current_data",
    "current_sha256",
    "storage_revision",
    "created_at",
    "updated_at",
}
SUMMARY_FIELDS = {
    "document_id",
    "title",
    "storage_revision",
    "current_sha256",
    "current_size_bytes",
    "created_at",
    "updated_at",
}


def imported(world, data=None, *, title="Synthetic DOCX", identity=None, scope="own"):
    return api().import_docx(
        world["runtimes"][scope],
        document_id=identity or uuid4(),
        title=title,
        data=raw() if data is None else data,
    )


def saved(world, stored, data, *, scope="own"):
    return api().save_docx(
        world["runtimes"][scope],
        document_id=stored.document_id,
        expected_storage_revision=stored.storage_revision,
        data=data,
    )


def assert_stored(value, identity, title, original, current, revision):
    assert isinstance(value, api().StoredDocx) and is_dataclass(value)
    assert {field.name for field in fields(value)} == STORED_FIELDS
    assert not hasattr(value, "__dict__")
    assert isinstance(value.document_id, UUID) and value.document_id == identity
    assert type(value.title) is str and value.title == title
    assert type(value.original_data) is bytes and value.original_data == original
    assert type(value.current_data) is bytes and value.current_data == current
    assert value.original_sha256 == sha256(original).hexdigest()
    assert value.current_sha256 == sha256(current).hexdigest()
    assert type(value.storage_revision) is int and value.storage_revision == revision
    for timestamp in (value.created_at, value.updated_at):
        assert isinstance(timestamp, datetime) and timestamp.utcoffset() is not None
    assert repr(original) not in repr(value) and repr(current) not in repr(value)


def assert_summary(value, stored):
    assert isinstance(value, api().DocxSummary) and is_dataclass(value)
    assert {field.name for field in fields(value)} == SUMMARY_FIELDS
    assert not hasattr(value, "__dict__")
    assert value.document_id == stored.document_id
    assert value.title == stored.title
    assert value.storage_revision == stored.storage_revision
    assert value.current_sha256 == stored.current_sha256
    assert type(value.current_size_bytes) is int and value.current_size_bytes == len(
        stored.current_data
    )
    assert value.created_at == stored.created_at and value.updated_at == stored.updated_at
    with pytest.raises(FrozenInstanceError):
        value.title = "changed only by caller"


def clock(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT clock_timestamp()"))


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_import_stores_exact_docx_and_returns_detached_immutable_snapshot(
    run_world, strict, encoding
):
    world = run_world
    original, _ = package(
        paragraph("Реле & sensor 😀"),
        strict=strict,
        encoding=encoding,
        main_part="custom/Requirements.XML",
        comment=b"exact-original PK\x05\x06 comment",
    )
    identity = uuid4()
    title = "  Exact title e\u0301 😀  "
    lower = clock(world["engine"])
    stored = imported(world, original, identity=identity, title=title)
    upper = clock(world["engine"])
    assert_stored(stored, identity, title, original, original, 1)
    assert lower <= stored.created_at <= upper
    assert lower <= stored.updated_at <= upper
    with pytest.raises(FrozenInstanceError):
        stored.current_data = b"changed by caller"
    assert api().get_docx(world["runtimes"]["own"], document_id=identity) == stored


def test_read_is_nonmutating_and_service_leaves_callers_engine_usable(run_world, monkeypatch):
    world = run_world
    stored = imported(world)
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().upper())

    def forbidden_dispose(*args, **kwargs):
        pytest.fail("DOCX storage does not own the caller's engine")

    event.listen(world["engine"], "before_cursor_execute", observe)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(world["engine"], "dispose", forbidden_dispose)
            assert (
                api().get_docx(world["runtimes"]["own"], document_id=stored.document_id) == stored
            )
            assert (
                api().get_docx(world["runtimes"]["own"], document_id=stored.document_id) == stored
            )
            with world["engine"].connect() as connection:
                assert connection.scalar(text("SELECT 1")) == 1
    finally:
        event.remove(world["engine"], "before_cursor_execute", observe)
    assert not any(item.startswith(("INSERT", "UPDATE", "DELETE", "MERGE")) for item in statements)


def test_same_source_with_new_id_creates_independent_documents(run_world):
    world = run_world
    original = raw("same original")
    first = imported(world, original, title="Same title")
    second = imported(world, original, title="Same title")
    assert first.document_id != second.document_id
    modified = saved(world, first, raw("changed first"))
    assert api().get_docx(world["runtimes"]["own"], document_id=first.document_id) == modified
    assert api().get_docx(world["runtimes"]["own"], document_id=second.document_id) == second
    assert len(api().list_docx(world["runtimes"]["own"])) == 2


def test_import_replay_returns_current_draft_without_resetting_revision_or_timestamps(run_world):
    world = run_world
    original = raw("imported original")
    first = imported(world, original, title=" Replay title ")
    second = saved(world, first, raw("first edit"))
    third = saved(world, second, raw("latest edit"))
    replay = imported(world, original, title=first.title, identity=first.document_id)
    assert replay == third
    assert_stored(replay, first.document_id, first.title, original, third.current_data, 3)
    with world["engine"].connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM docx_documents")) == 1


@pytest.mark.parametrize("altered", ["title", "package"])
def test_import_replay_rejects_changed_title_or_bytes_and_retains_existing_draft(
    run_world, altered
):
    world = run_world
    original, _ = package(paragraph("same visible text"), comment=b"first package")
    first = imported(world, original, title=" Original title ")
    current = saved(world, first, raw("saved draft"))
    title = first.title if altered == "package" else first.title.strip()
    alternate, _ = package(paragraph("same visible text"), comment=b"another package")
    data = alternate if altered == "package" else original
    error_type = import_module("ara.documents.storage").DocumentError
    with pytest.raises(error_type) as caught:
        imported(world, data, title=title, identity=first.document_id)
    assert (caught.value.status, caught.value.code, caught.value.retryable) == (
        409,
        "import_conflict",
        False,
    )
    assert api().get_docx(world["runtimes"]["own"], document_id=first.document_id) == current
    assert imported(world, original, title=first.title, identity=first.document_id) == current


def test_save_preserves_original_and_same_bytes_still_create_new_storage_revision(run_world):
    world = run_world
    original, replacement = raw("original"), raw("replacement")
    first = imported(world, original)
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE docx_documents SET updated_at='2000-01-01 00:00:00+00' WHERE id=:id"),
            {"id": first.document_id},
        )
    lower = clock(world["engine"])
    second = saved(world, first, replacement)
    upper = clock(world["engine"])
    assert_stored(second, first.document_id, first.title, original, replacement, 2)
    assert second.created_at == first.created_at
    assert lower <= second.updated_at <= upper
    lower = clock(world["engine"])
    third = saved(world, second, replacement)
    upper = clock(world["engine"])
    assert_stored(third, first.document_id, first.title, original, replacement, 3)
    assert third.created_at == first.created_at
    assert lower <= third.updated_at <= upper
    assert first.current_data == original and first.storage_revision == 1


def test_empty_docx_lists_do_not_include_legacy_markdown_documents(run_world):
    world = run_world
    assert len(world["documents"]) == 4
    for scope in ("own", "peer", "foreign"):
        result = api().list_docx(world["runtimes"][scope])
        assert type(result) is tuple and result == ()


def test_list_scopes_include_only_documents_of_the_exact_runtime_project(run_world):
    world = run_world
    documents = {
        scope: imported(world, raw(scope), title="Identical title", scope=scope)
        for scope in ("own", "peer", "foreign")
    }
    for scope, stored in documents.items():
        summaries = api().list_docx(world["runtimes"][scope])
        assert type(summaries) is tuple and len(summaries) == 1
        assert_summary(summaries[0], stored)
        assert api().get_docx(world["runtimes"][scope], document_id=stored.document_id) == stored


def test_list_orders_by_created_then_uuid_and_paginates_without_selecting_binary_data(run_world):
    world = run_world
    stored = {
        index: imported(world, raw(str(index)), identity=UUID(int=index), title=f"Title {index}")
        for index in (4, 2, 1, 3)
    }
    with world["engine"].begin() as connection:
        for index, item in stored.items():
            connection.execute(
                text("UPDATE docx_documents SET created_at=:created WHERE id=:id"),
                {
                    "id": item.document_id,
                    "created": datetime(2000 + index % 2, 1, 1, tzinfo=timezone.utc),
                },
            )
    stored = {
        index: api().get_docx(world["runtimes"]["own"], document_id=item.document_id)
        for index, item in stored.items()
    }
    statements, result_types = [], []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
        result_types.extend(column.type_code for column in (cursor.description or ()))

    event.listen(world["engine"], "after_cursor_execute", observe)
    try:
        all_items = api().list_docx(world["runtimes"]["own"])
        first_page = api().list_docx(world["runtimes"]["own"], limit=2, offset=0)
        next_page = api().list_docx(world["runtimes"]["own"], limit=2, offset=2)
        assert api().list_docx(world["runtimes"]["own"], limit=2, offset=4) == ()
    finally:
        event.remove(world["engine"], "after_cursor_execute", observe)
    assert [item.document_id.int for item in all_items] == [3, 1, 4, 2]
    assert first_page + next_page == all_items
    for item in all_items:
        assert_summary(item, stored[item.document_id.int])
    assert 17 not in result_types, "PostgreSQL BYTEA must not be selected by list_docx"
    assert any("octet_length" in statement for statement in statements)


def test_list_metadata_tracks_saved_bytes_without_changing_creation_order(run_world):
    world = run_world
    older = imported(world, raw("older"))
    newer = imported(world, raw("newer"))
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE docx_documents SET created_at='2000-01-01 00:00:00+00' WHERE id=:id"),
            {"id": older.document_id},
        )
    older = api().get_docx(world["runtimes"]["own"], document_id=older.document_id)
    replacement = package(paragraph("changed older"), comment=b"x" * 81)[0]
    changed = saved(world, older, replacement)
    listed = api().list_docx(world["runtimes"]["own"])
    assert [item.document_id for item in listed] == [newer.document_id, older.document_id]
    assert_summary(listed[0], newer)
    assert_summary(listed[1], changed)


def test_saved_document_restores_identically_through_a_fresh_engine(run_world):
    world = run_world
    first = imported(world, raw("stored original"), title="Persistent title")
    expected = saved(world, first, raw("stored current"))
    replacement_engine = create_engine(
        world["engine"].url, poolclass=NullPool, hide_parameters=True
    )
    try:
        runtime = replace(world["runtimes"]["own"], engine=replacement_engine)
        actual = api().get_docx(runtime, document_id=first.document_id)
        assert actual == expected
        assert_summary(api().list_docx(runtime)[0], expected)
    finally:
        replacement_engine.dispose()
    with world["engine"].connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1


def test_separate_python_process_recovers_exact_original_current_and_metadata(run_world):
    world = run_world
    expected = saved(world, imported(world, raw("process original")), raw("process current"))
    url = world["engine"].url
    assert url.database.startswith("ara_check_") and url.password is None
    payload = {
        "username": url.username,
        "database": url.database,
        "socket": url.query["host"],
        "owner": str(world["runtimes"]["own"].user_id),
        "project": str(world["runtimes"]["own"].project_id),
        "document": str(expected.document_id),
    }
    script = """
import base64, json, sys
from uuid import UUID
from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool
sys.path.insert(0, sys.argv[1])
from ara.documents.runtime import DocumentRuntime
from ara.docx_documents import get_docx
p = json.loads(sys.stdin.read())
assert p['database'].startswith('ara_check_')
engine = create_engine(URL.create('postgresql+psycopg', username=p['username'],
    database=p['database'], query={'host': p['socket'], 'connect_timeout': '5'}),
    poolclass=NullPool, hide_parameters=True)
try:
    runtime = DocumentRuntime(engine=engine, user_id=UUID(p['owner']),
        project_id=UUID(p['project']), mode='local')
    row = get_docx(runtime, document_id=UUID(p['document']))
    print(json.dumps({'id': str(row.document_id), 'title': row.title,
        'original': base64.b64encode(row.original_data).decode('ascii'),
        'current': base64.b64encode(row.current_data).decode('ascii'),
        'original_sha256': row.original_sha256, 'current_sha256': row.current_sha256,
        'revision': row.storage_revision, 'created_at': row.created_at.isoformat(),
        'updated_at': row.updated_at.isoformat()}))
finally:
    engine.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(ROOT / "src")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    restored = json.loads(result.stdout)
    assert restored == {
        "id": str(expected.document_id),
        "title": expected.title,
        "original": base64.b64encode(expected.original_data).decode("ascii"),
        "current": base64.b64encode(expected.current_data).decode("ascii"),
        "original_sha256": expected.original_sha256,
        "current_sha256": expected.current_sha256,
        "revision": expected.storage_revision,
        "created_at": expected.created_at.isoformat(),
        "updated_at": expected.updated_at.isoformat(),
    }


def test_storage_and_session_revisions_are_independent_and_saving_does_not_mark_session_saved(
    run_world,
):
    world = run_world
    first = imported(world, raw("A"))
    sessions = import_module("ara.docx_package.session")
    session = sessions.DocxSession(first.current_data)
    for replacement in ("B", "C", "D"):
        snapshot = session.snapshot()
        span = text_spans(snapshot.projection)[0]
        session.apply(
            (change(span, 0, span, len(span.text), span.text, replacement),),
            expected_revision=snapshot.revision,
        )
    snapshot = session.snapshot()
    assert snapshot.revision == 3 and snapshot.is_dirty
    persisted = saved(world, first, snapshot.data)
    assert persisted.storage_revision == 2
    assert session.snapshot().revision == 3 and session.snapshot().is_dirty
    assert session.mark_saved(expected_revision=3).is_dirty is False
    reopened = sessions.DocxSession(
        api().get_docx(world["runtimes"]["own"], document_id=first.document_id).current_data
    )
    clean = reopened.snapshot()
    assert (clean.revision, clean.undo_depth, clean.redo_depth, clean.is_dirty) == (0, 0, 0, False)
    span = text_spans(clean.projection)[0]
    assert span.anchor.source_sha256 == persisted.current_sha256
    edited = reopened.apply((change(span, 0, span, 1, "D", "E"),), expected_revision=0)
    final = saved(world, persisted, edited.data)
    assert final.storage_revision == 3 and edited.revision == 1
    assert final.original_data == first.original_data


def test_immutable_imported_original_survives_session_history_eviction(run_world):
    world = run_world
    original = raw("original before editing")
    first = imported(world, original)
    sessions = import_module("ara.docx_package.session")
    session = sessions.DocxSession(
        original, session_limits=sessions.SessionLimits(max_history_states=1)
    )
    snapshot = session.snapshot()
    span = text_spans(snapshot.projection)[0]
    edited = session.apply(
        (change(span, 0, span, len(span.text), span.text, "final"),), expected_revision=0
    )
    assert edited.undo_depth == 0
    expected = saved(world, first, edited.data)
    restored = api().get_docx(world["runtimes"]["own"], document_id=first.document_id)
    assert restored == expected
    assert restored.original_data == original and restored.current_data == edited.data


def test_rich_source_import_session_save_reopen_and_replay_preserve_expected_bytes(run_world):
    world = run_world
    original = FIXTURE.read_bytes()
    first = imported(world, original, title="Rich synthetic control")
    sessions = import_module("ara.docx_package.session")
    session = sessions.DocxSession(first.current_data)
    initial = session.snapshot()
    phrase = initial.projection.blocks[4].spans
    link = next(span for span in text_spans(initial.projection) if span.hyperlink is not None)
    table = next(block for block in initial.projection.blocks if block.kind == "table")
    cell = table.rows[1].cells[0].blocks[0].spans[0]
    edits = (
        change(
            phrase[0], 9, phrase[2], 6, "keeps a stable canonical type even ", "retains its type "
        ),
        change(link, 0, link, 9, "Synthetic", "Example"),
        change(cell, 0, cell, 1, cell.text[:1], "Q"),
    )
    expected_bytes = import_module("ara.docx_package.ranges").export_docx_ranges(original, edits)
    current = session.apply(edits, expected_revision=0)
    assert current.data == expected_bytes
    persisted = saved(world, first, current.data)
    assert session.snapshot().is_dirty
    session.mark_saved(expected_revision=1)
    replacement_engine = create_engine(
        world["engine"].url, poolclass=NullPool, hide_parameters=True
    )
    try:
        restored = api().get_docx(
            replace(world["runtimes"]["own"], engine=replacement_engine),
            document_id=first.document_id,
        )
    finally:
        replacement_engine.dispose()
    assert_stored(restored, first.document_id, first.title, original, expected_bytes, 2)
    assert restored == persisted
    reopened = sessions.DocxSession(restored.current_data).snapshot()
    assert reopened.data == expected_bytes and reopened.revision == 0 and not reopened.is_dirty
    assert reopened.undo_depth == reopened.redo_depth == 0
    assert all(
        span.anchor.source_sha256 == restored.current_sha256
        for span in text_spans(reopened.projection)
    )
    before, after = zip_parts(original), zip_parts(expected_bytes)
    assert {name: data for name, data in before.items() if name != MAIN} == {
        name: data for name, data in after.items() if name != MAIN
    }
    assert imported(world, original, identity=first.document_id, title=first.title) == restored
