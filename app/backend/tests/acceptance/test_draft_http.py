"""Independent D01-02 acceptance of persisted drafts through real local HTTP routes."""

from dataclasses import replace
from datetime import datetime
from importlib import import_module
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

PRIVATE = "SYNTHETIC_HTTP_DRAFT_PRIVATE_b28a"
FIELDS = {"document_id", "base_version_id", "revision", "content_markdown", "updated_at"}
SOURCE_TABLES = (
    "users",
    "projects",
    "documents",
    "document_versions",
    "context_revisions",
    "analysis_runs",
    "analysis_attempts",
    "review_revisions",
)


def _ids(world, name="own"):
    document = world["documents"][name]
    return document["id"], document["current_version_id"]


def _path(document):
    return f"/documents/{document}/draft"


def _body(world, expected=0, content=PRIVATE, *, name="own", base=None):
    return {
        "expected_revision": expected,
        "base_version_id": _ids(world, name)[1] if base is None else base,
        "content_markdown": content,
    }


def _client(runtime):
    create_app = import_module("ara.app").create_app
    return TestClient(create_app(document_runtime=runtime), raise_server_exceptions=False)


def _snapshot(response, document, base, revision, content):
    assert response.status_code == 200, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    snapshot = response.json()
    assert set(snapshot) == FIELDS
    for field, expected in (("document_id", document), ("base_version_id", base)):
        assert type(snapshot[field]) is str
        assert snapshot[field] == str(UUID(snapshot[field])) == str(UUID(str(expected)))
    assert type(snapshot["revision"]) is int and snapshot["revision"] == revision > 0
    assert type(snapshot["content_markdown"]) is str and snapshot["content_markdown"] == content
    assert type(snapshot["updated_at"]) is str
    assert datetime.fromisoformat(snapshot["updated_at"]).utcoffset() is not None
    return snapshot


def _error(response, status, code, *, request_ids=None, forbidden=()):
    assert response.status_code == status, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    payload = response.json()
    assert set(payload) == {"code", "message", "retryable", "request_id"}
    assert payload["code"] == code and payload["retryable"] is False
    assert isinstance(payload["message"], str) and payload["message"]
    assert isinstance(payload["request_id"], str)
    assert str(UUID(payload["request_id"])) == payload["request_id"]
    if request_ids is not None:
        assert payload["request_id"] not in request_ids
        request_ids.add(payload["request_id"])
    for value in (PRIVATE, *forbidden):
        assert str(value) not in response.text
    if status == 404:
        assert payload["message"] == import_module("ara.documents.storage")._not_found().message
    return payload["message"]


def _sources(engine):
    with engine.connect() as connection:
        return {
            table: connection.execute(
                text(f"SELECT row_to_json(source) FROM {table} AS source ORDER BY id")
            )
            .scalars()
            .all()
            for table in SOURCE_TABLES
        }


def _drafts(engine):
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text("SELECT * FROM document_drafts ORDER BY document_id")
            ).mappings()
        ]


def test_http_missing_draft_returns_literal_null_without_writes(run_world):
    world = run_world
    before = _sources(world["engine"])
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().upper())

    event.listen(world["engine"], "before_cursor_execute", observe)
    try:
        for name, scope in (("own", "own"), ("second", "own"), ("peer", "peer")):
            with world["client"](scope) as client:
                for _ in range(2):
                    response = client.get(_path(_ids(world, name)[0]))
                    assert response.status_code == 200, response.text
                    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
                    assert response.json() is None
                    assert response.content.strip() == b"null"
    finally:
        event.remove(world["engine"], "before_cursor_execute", observe)
    assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE", "MERGE")) for sql in statements)
    assert _drafts(world["engine"]) == []
    assert _sources(world["engine"]) == before


def test_http_snapshot_matches_committed_row_and_survives_new_app_and_engine(run_world):
    world = run_world
    document, base = _ids(world)
    content = "# Незавершённый документ 🧪\r\n\r\n  Exact text\t\n"
    with world["client"]() as client:
        saved = _snapshot(
            client.put(_path(document), json=_body(world, content=content)),
            document,
            base,
            1,
            content,
        )
        assert _snapshot(client.get(_path(document)), document, base, 1, content) == saved
    rows = _drafts(world["engine"])
    assert len(rows) == 1
    stored = rows[0]
    assert set(stored) == FIELDS
    assert str(stored["document_id"]) == document
    assert str(stored["base_version_id"]) == base
    assert stored["revision"] == 1 and stored["content_markdown"] == content
    assert stored["updated_at"] == datetime.fromisoformat(saved["updated_at"])
    replacement = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        with world["client"](engine=replacement) as restarted:
            assert _snapshot(restarted.get(_path(document)), document, base, 1, content) == saved
        with replacement.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        replacement.dispose()


def test_http_preserves_empty_whitespace_unicode_crlf_unclosed_and_long_text(run_world):
    world = run_world
    document, base = _ids(world)
    contents = (
        "",
        " \t\r\n \n\t",
        "e\u0301 / é / 日本語 / 🧑🏽‍💻 / \ufeff / \u2028",
        "# Heading\r\n\r\nParagraph  \r\n- item\r\n",
        "```python\r\nif True:\n  unfinished\r\n",
        "x" * 1_000_001 + "\r\nЯ🧪",
        "",
    )
    with world["client"]() as client:
        for expected, content in enumerate(contents):
            saved = _snapshot(
                client.put(_path(document), json=_body(world, expected, content)),
                document,
                base,
                expected + 1,
                content,
            )
            assert (
                _snapshot(client.get(_path(document)), document, base, expected + 1, content)
                == saved
            )
            stored = _drafts(world["engine"])
            assert len(stored) == 1 and stored[0]["content_markdown"] == content
    replacement = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        with world["client"](engine=replacement) as restarted:
            assert (
                _snapshot(restarted.get(_path(document)), document, base, len(contents), "")
                == saved
            )
    finally:
        replacement.dispose()


def test_http_cas_replay_same_content_and_full_replacement(run_world):
    world = run_world
    document, base = _ids(world)
    request_ids, messages = set(), set()
    with world["client"]() as client:
        messages.add(
            _error(
                client.put(_path(document), json=_body(world, expected=1)),
                409,
                "draft_conflict",
                request_ids=request_ids,
            )
        )
        assert client.get(_path(document)).json() is None
        saved = _snapshot(
            client.put(_path(document), json=_body(world)), document, base, 1, PRIVATE
        )
        for expected in (0, 2, 9223372036854775806):
            messages.add(
                _error(
                    client.put(_path(document), json=_body(world, expected=expected)),
                    409,
                    "draft_conflict",
                    request_ids=request_ids,
                )
            )
            assert client.get(_path(document)).json() == saved
        same = _snapshot(
            client.put(_path(document), json=_body(world, expected=1)),
            document,
            base,
            2,
            PRIVATE,
        )
        assert client.get(_path(document)).json() == same
        shortened = _snapshot(
            client.put(_path(document), json=_body(world, expected=2, content="Short")),
            document,
            base,
            3,
            "Short",
        )
        for expected in (0, 1, 2, 4):
            messages.add(
                _error(
                    client.put(_path(document), json=_body(world, expected, "Short")),
                    409,
                    "draft_conflict",
                    request_ids=request_ids,
                )
            )
            assert client.get(_path(document)).json() == shortened
    assert len(messages) == 1
    assert len(_drafts(world["engine"])) == 1


def test_http_historical_base_and_explicit_base_change_preserve_versions(run_world):
    world = run_world
    document, old_base = _ids(world)
    with world["client"]() as client:
        first = _snapshot(
            client.put(_path(document), json=_body(world)), document, old_base, 1, PRIVATE
        )
    latest = import_module("ara.documents.storage").append_version(
        world["runtimes"]["own"],
        document_id=UUID(document),
        expected_version_id=UUID(old_base),
        content_markdown="Separately saved newer version\n",
    )
    before = _sources(world["engine"])
    with world["client"]() as client:
        assert client.get(_path(document)).json() == first
        for expected, base, content in (
            (1, old_base, "Still an older-base draft"),
            (2, str(latest.id), "Explicit newer base"),
            (3, old_base, "Explicit older base"),
        ):
            saved = _snapshot(
                client.put(_path(document), json=_body(world, expected, content, base=base)),
                document,
                base,
                expected + 1,
                content,
            )
            assert client.get(_path(document)).json() == saved
    assert _sources(world["engine"]) == before


def test_http_wrong_base_and_unknown_document_return_same_safe_not_found(run_world):
    world = run_world
    document, base = _ids(world)
    request_ids, messages = set(), set()
    with world["client"]() as client:
        saved = _snapshot(
            client.put(_path(document), json=_body(world)), document, base, 1, PRIVATE
        )
        before_sources, before_drafts = _sources(world["engine"]), _drafts(world["engine"])
        for invalid_base in (
            str(uuid4()),
            *(_ids(world, name)[1] for name in ("second", "peer", "foreign")),
        ):
            for expected in (0, 1, 999):
                messages.add(
                    _error(
                        client.put(_path(document), json=_body(world, expected, base=invalid_base)),
                        404,
                        "not_found",
                        request_ids=request_ids,
                        forbidden=(document, invalid_base),
                    )
                )
            assert client.get(_path(document)).json() == saved
        unknown = str(uuid4())
        messages.add(
            _error(
                client.get(_path(unknown)),
                404,
                "not_found",
                request_ids=request_ids,
                forbidden=(unknown,),
            )
        )
        messages.add(
            _error(
                client.put(_path(unknown), json=_body(world)),
                404,
                "not_found",
                request_ids=request_ids,
                forbidden=(unknown, base),
            )
        )
    assert len(messages) == 1
    assert _sources(world["engine"]) == before_sources
    assert _drafts(world["engine"]) == before_drafts


def test_http_scope_is_server_owned_and_headers_or_query_cannot_expand_access(run_world):
    world = run_world
    for name, scope in (("own", "own"), ("peer", "peer"), ("foreign", "foreign")):
        document, base = _ids(world, name)
        with world["client"](scope) as client:
            _snapshot(
                client.put(_path(document), json=_body(world, name=name)),
                document,
                base,
                1,
                PRIVATE,
            )
    before_sources, before_drafts = _sources(world["engine"]), _drafts(world["engine"])
    request_ids, messages = set(), set()
    for scope, name in (("own", "peer"), ("own", "foreign"), ("peer", "own"), ("foreign", "own")):
        document, base = _ids(world, name)
        target_scope = "own" if name == "own" else name
        target = world["runtimes"][target_scope]
        supplied_request_id = str(uuid4())
        headers = {
            "X-User-ID": str(target.user_id),
            "X-Project-ID": str(target.project_id),
            "User-ID": str(target.user_id),
            "Project-ID": str(target.project_id),
            "X-Request-ID": supplied_request_id,
        }
        params = {"user_id": str(target.user_id), "project_id": str(target.project_id)}
        with world["client"](scope) as client:
            responses = [client.get(_path(document), headers=headers, params=params)]
            for expected, requested_base in ((1, base), (999, str(uuid4()))):
                responses.append(
                    client.put(
                        _path(document),
                        json=_body(world, expected, base=requested_base),
                        headers=headers,
                        params=params,
                    )
                )
            for response in responses:
                messages.add(
                    _error(
                        response,
                        404,
                        "not_found",
                        request_ids=request_ids,
                        forbidden=(
                            document,
                            base,
                            supplied_request_id,
                            target.user_id,
                            target.project_id,
                        ),
                    )
                )
    assert len(messages) == 1
    assert _sources(world["engine"]) == before_sources
    assert _drafts(world["engine"]) == before_drafts


def test_http_project_owner_transfer_preserves_draft_and_revokes_old_owner(run_world):
    world = run_world
    document, base = _ids(world)
    with world["client"]() as original:
        saved = _snapshot(
            original.put(_path(document), json=_body(world)), document, base, 1, PRIVATE
        )
        with world["engine"].begin() as connection:
            connection.execute(
                text("UPDATE projects SET owner_id=:owner WHERE id=:project"),
                {"owner": world["owners"]["foreign"], "project": world["projects"]["own"]},
            )
        before = _sources(world["engine"])
        _error(original.get(_path(document)), 404, "not_found")
        _error(original.put(_path(document), json=_body(world, expected=1)), 404, "not_found")
    new_owner = replace(world["runtimes"]["own"], user_id=world["owners"]["foreign"])
    with _client(new_owner) as client:
        assert client.get(_path(document)).json() == saved
        updated = _snapshot(
            client.put(_path(document), json=_body(world, 1, "New owner's draft")),
            document,
            base,
            2,
            "New owner's draft",
        )
        assert client.get(_path(document)).json() == updated
    assert _sources(world["engine"]) == before


def test_http_document_project_transfer_requires_matching_runtime(run_world):
    world = run_world
    document, base = _ids(world)
    with world["client"]() as original:
        saved = _snapshot(
            original.put(_path(document), json=_body(world)), document, base, 1, PRIVATE
        )
        with world["engine"].begin() as connection:
            connection.execute(
                text("UPDATE documents SET project_id=:project WHERE id=:document"),
                {"project": world["projects"]["peer"], "document": UUID(document)},
            )
        before = _sources(world["engine"])
        _error(original.get(_path(document)), 404, "not_found")
        _error(original.put(_path(document), json=_body(world, expected=1)), 404, "not_found")
    with world["client"]("peer") as client:
        assert client.get(_path(document)).json() == saved
        updated = _snapshot(
            client.put(_path(document), json=_body(world, 1, "Moved draft")),
            document,
            base,
            2,
            "Moved draft",
        )
        assert client.get(_path(document)).json() == updated
    assert _sources(world["engine"]) == before


def test_http_draft_operations_preserve_all_eight_populated_source_tables(review_world):
    world = review_world
    with world["client"]() as client:
        review_path = f"/runs/{world['runs']['own']['run_id']}/review"
        response = client.get(review_path)
        assert response.status_code == 200, response.text
        review = response.json()
        response = client.put(
            review_path,
            json={
                "expected_revision_id": review["revision_id"],
                "expected_result_fingerprint": review["result_fingerprint"],
                "decisions": review["decisions"],
            },
        )
        assert response.status_code == 200, response.text
        before = _sources(world["engine"])
        assert all(before.values()), "Every source table needs synthetic evidence"
        for name in ("own", "second"):
            document, base = _ids(world, name)
            response = client.get(_path(document))
            assert response.status_code == 200 and response.json() is None
            _snapshot(
                client.put(_path(document), json=_body(world, name=name)),
                document,
                base,
                1,
                PRIVATE,
            )
            updated = _snapshot(
                client.put(_path(document), json=_body(world, 1, "", name=name)),
                document,
                base,
                2,
                "",
            )
            _error(client.put(_path(document), json=_body(world, name=name)), 409, "draft_conflict")
            assert client.get(_path(document)).json() == updated
    assert len(_drafts(world["engine"])) == 2
    assert _sources(world["engine"]) == before


def test_http_accepts_python_uuid_string_forms_and_returns_canonical_ids(run_world):
    world = run_world
    document, base = _ids(world)
    document_id, base_id = UUID(document), UUID(base)
    forms = (
        (document.upper(), base.upper()),
        (document_id.hex, base_id.hex),
        ("{" + document + "}", "{" + base + "}"),
        (document_id.urn, base_id.urn),
    )
    with world["client"]() as client:
        for expected, (path_id, body_id) in enumerate(forms):
            saved = _snapshot(
                client.put(_path(path_id), json=_body(world, expected, base=body_id)),
                document,
                base,
                expected + 1,
                PRIVATE,
            )
            assert client.get(_path(path_id)).json() == saved
            assert client.get(_path(document)).json() == saved


def test_http_bigint_revision_boundary_preserves_exact_json_integer(run_world):
    world = run_world
    document, base = _ids(world)
    before = _sources(world["engine"])
    import_module("ara.drafts").save_draft(
        world["runtimes"]["own"],
        document_id=UUID(document),
        expected_revision=0,
        base_version_id=UUID(base),
        content_markdown="Synthetic draft before the BIGINT boundary",
    )
    expected = 9223372036854775806
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE document_drafts SET revision=:revision WHERE document_id=:document"),
            {"revision": expected, "document": UUID(document)},
        )
    content = "Exact final BIGINT revision\r\n"
    with world["client"]() as client:
        saved = _snapshot(
            client.put(_path(document), json=_body(world, expected, content)),
            document,
            base,
            9223372036854775807,
            content,
        )
        assert (
            _snapshot(client.get(_path(document)), document, base, 9223372036854775807, content)
            == saved
        )
    rows = _drafts(world["engine"])
    assert len(rows) == 1
    assert type(rows[0]["revision"]) is int and rows[0]["revision"] == 9223372036854775807
    assert rows[0]["content_markdown"] == content
    assert _sources(world["engine"]) == before
