"""Independent HTTP and real PostgreSQL acceptance for document creation."""

import json
from datetime import datetime
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

MARKDOWN = (
    "# Требование\r\n\r\n| Имя | Тип |\r\n| --- | --- |\r\n| Свет | Реле |\r\n\r\n"
    "```json\r\n{}\r\n```"
)
PRIVATE = "SYNTHETIC_PRIVATE_CONTENT_629d"


@pytest.fixture
def world(pg_engine):
    ids = {key: uuid4() for key in ("user", "other_user", "project", "peer", "foreign")}
    with pg_engine.begin() as connection:
        for key in ("user", "other_user"):
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": ids[key]})
        for project, owner in (("project", "user"), ("peer", "user"), ("foreign", "other_user")):
            connection.execute(
                text("INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, :name)"),
                {"id": ids[project], "owner": ids[owner], "name": "Synthetic project"},
            )
    return ids


def _client(engine, user, project):
    create_app = import_module("ara.app").create_app
    document_runtime = import_module("ara.documents.runtime").DocumentRuntime

    runtime = document_runtime(engine=engine, user_id=user, project_id=project, mode="local")
    return TestClient(create_app(document_runtime=runtime), raise_server_exceptions=False)


def _create(client, title="  Synthetic title  ", content=MARKDOWN, **request_options):
    response = client.post(
        "/documents", json={"title": title, "content_markdown": content}, **request_options
    )
    assert response.status_code == 201, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    summary = response.json()
    assert set(summary) == {"id", "title", "current_version_id", "created_at"}
    assert summary["title"] == title
    assert UUID(summary["id"])
    assert UUID(summary["current_version_id"])
    assert datetime.fromisoformat(summary["created_at"]).utcoffset() is not None
    return summary


def _version_path(summary):
    return f"/documents/{summary['id']}/versions/{summary['current_version_id']}"


def _error(response, status, code, retryable):
    assert response.status_code == status, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    body = response.json()
    assert set(body) == {"code", "message", "retryable", "request_id"}
    assert body["code"] == code
    assert body["retryable"] is retryable
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["request_id"], str) and body["request_id"]
    assert body["request_id"] != "untrusted-client-request-id"
    assert PRIVATE not in response.text
    return {key: value for key, value in body.items() if key != "request_id"}


def test_create_list_read_persists_exact_content_across_app_and_engine(pg_engine, world):
    with _client(pg_engine, world["user"], world["project"]) as client:
        assert client.get("/documents").json() == {"items": []}
        summary = _create(client)
        assert client.get("/documents").json() == {"items": [summary]}
        response = client.get(_version_path(summary))
        assert response.status_code == 200
        version = response.json()
        assert set(version) == {
            "id",
            "document_id",
            "parent_version_id",
            "content_markdown",
            "blocks",
            "provenance",
            "import_omissions",
            "created_at",
        }
        assert version["id"] == summary["current_version_id"]
        assert version["document_id"] == summary["id"]
        assert version["parent_version_id"] is None
        assert version["content_markdown"] == MARKDOWN
        assert version["provenance"] == {"source": "manual"}
        assert version["import_omissions"] == []
        assert datetime.fromisoformat(version["created_at"]).utcoffset() is not None
        assert "".join(block["text"] for block in version["blocks"]) == MARKDOWN
        assert {block["kind"] for block in version["blocks"]} == {"heading", "table", "code"}
        table = next(block for block in version["blocks"] if block["kind"] == "table")
        code = next(block for block in version["blocks"] if block["kind"] == "code")
        assert table["text"].strip() == "| Имя | Тип |\r\n| --- | --- |\r\n| Свет | Реле |"
        assert code["text"].strip() == "```json\r\n{}\r\n```"
        block_ids = [block["id"] for block in version["blocks"]]
        assert block_ids and all(block_ids) and len(set(block_ids)) == len(block_ids)
    replacement = create_engine(pg_engine.url, poolclass=NullPool, hide_parameters=True)
    try:
        with _client(replacement, world["user"], world["project"]) as client:
            assert client.get(_version_path(summary)).json() == version
            assert client.get("/documents").json() == {"items": [summary]}
    finally:
        replacement.dispose()
    with pg_engine.connect() as connection:
        saved = connection.execute(
            text("SELECT project_id, title, source_url FROM documents WHERE id = :id"),
            {"id": UUID(summary["id"])},
        ).one()
        assert tuple(saved) == (world["project"], summary["title"], None)


def test_project_isolation_spoofing_and_indistinguishable_404(pg_engine, world):
    saved = {}
    for key, owner in (("project", "user"), ("peer", "user"), ("foreign", "other_user")):
        with _client(pg_engine, world[owner], world[key]) as client:
            saved[key] = _create(client, title=key, content=PRIVATE)
    spoof = {
        "headers": {
            "X-User-ID": str(world["other_user"]),
            "X-Owner-ID": str(world["other_user"]),
            "X-Project-ID": str(world["foreign"]),
            "X-Request-ID": "untrusted-client-request-id",
        },
        "params": {
            "user_id": str(world["other_user"]),
            "owner_id": str(world["other_user"]),
            "project_id": str(world["foreign"]),
        },
    }
    failures = []
    with _client(pg_engine, world["user"], world["project"]) as client:
        assert client.get("/documents", **spoof).json() == {"items": [saved["project"]]}
        for path in (
            _version_path(saved["peer"]),
            _version_path(saved["foreign"]),
            f"/documents/{uuid4()}/versions/{uuid4()}",
            f"/documents/{saved['project']['id']}/versions/{saved['peer']['current_version_id']}",
        ):
            failures.append(_error(client.get(path, **spoof), 404, "not_found", False))
        created = _create(client, title="Server-owned", **spoof)
        mismatched = f"/documents/{saved['project']['id']}/versions/{created['current_version_id']}"
        failures.append(_error(client.get(mismatched, **spoof), 404, "not_found", False))
    with pg_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT project_id FROM documents WHERE id = :id"),
                {"id": UUID(created["id"])},
            ).scalar_one()
            == world["project"]
        )
    for user, project in ((world["other_user"], world["project"]), (world["user"], uuid4())):
        with _client(pg_engine, user, project) as client:
            responses = [
                client.get("/documents"),
                client.get(_version_path(saved["project"])),
                client.post("/documents", json={"title": PRIVATE, "content_markdown": PRIVATE}),
            ]
            failures.extend(_error(response, 404, "not_found", False) for response in responses)
    assert all(failure == failures[0] for failure in failures)


def test_list_order_default_limit_offsets_and_bounds(pg_engine, world):
    ids = [uuid4() for _ in range(53)]
    with pg_engine.begin() as connection:
        for document_id in ids:
            version_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO documents (id, project_id, title) VALUES (:id, :project, 'Page')"
                ),
                {"id": document_id, "project": world["project"]},
            )
            connection.execute(
                text(
                    "INSERT INTO document_versions (id, document_id, content_markdown) "
                    "VALUES (:id, :document, 'Synthetic')"
                ),
                {"id": version_id, "document": document_id},
            )
            connection.execute(
                text("UPDATE documents SET current_version_id = :version WHERE id = :id"),
                {"id": document_id, "version": version_id},
            )
        connection.execute(
            text("UPDATE documents SET created_at = created_at - interval '1 day' WHERE id = :id"),
            {"id": ids[0]},
        )
    expected = [str(value) for value in sorted(ids[1:], reverse=True)] + [str(ids[0])]
    with _client(pg_engine, world["user"], world["project"]) as client:
        assert [row["id"] for row in client.get("/documents").json()["items"]] == expected[:50]
        page = client.get("/documents", params={"limit": 4, "offset": 49})
        assert [row["id"] for row in page.json()["items"]] == expected[49:53]
        assert client.get("/documents", params={"offset": 53}).json() == {"items": []}
        for parameters in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "bad"}):
            _error(client.get("/documents", params=parameters), 422, "validation_error", False)


def test_invalid_input_returns_safe_422_without_writing(pg_engine, world):
    base = {"title": PRIVATE, "content_markdown": PRIVATE}
    invalid = [
        {},
        {"title": " "},
        {"content_markdown": "\r\n\t"},
        {"title": None},
        {"title": 7},
        {"content_markdown": ["text"]},
        {"title": "a\x00b"},
        {"content_markdown": "a\x00b"},
        {"title": "\ud800"},
        {"content_markdown": "\udfff"},
        {"title": "x" * 201},
        {"content_markdown": "x" * 1_000_001},
    ]
    bodies = [{}] + [{**base, **replacement} for replacement in invalid[1:]]
    for field in (
        "owner_id",
        "user_id",
        "project_id",
        "id",
        "current_version_id",
        "blocks",
        "provenance",
        "source_url",
    ):
        bodies.append({**base, field: str(uuid4())})
    with _client(pg_engine, world["user"], world["project"]) as client:
        for body in bodies:
            response = client.post(
                "/documents",
                content=json.dumps(body, ensure_ascii=True).encode("ascii"),
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": "untrusted-client-request-id",
                },
            )
            _error(response, 422, "validation_error", False)
        _error(
            client.get("/documents/not-a-uuid/versions/not-a-uuid"), 422, "validation_error", False
        )
    with pg_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM document_versions")).scalar_one() == 0


@pytest.mark.parametrize("failure_step", ["version_insert", "current_update"])
def test_creation_rolls_back_every_row_when_a_write_fails(pg_engine, world, failure_step):
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION ara_test_reject_write() RETURNS trigger LANGUAGE plpgsql AS $$ "
                f"BEGIN RAISE EXCEPTION '{PRIVATE}'; END $$"
            )
        )
        target = (
            "BEFORE INSERT ON document_versions"
            if failure_step == "version_insert"
            else "BEFORE UPDATE OF current_version_id ON documents"
        )
        connection.execute(
            text(
                f"CREATE TRIGGER ara_test_write_failure {target} "
                "FOR EACH ROW EXECUTE FUNCTION ara_test_reject_write()"
            )
        )
    with _client(pg_engine, world["user"], world["project"]) as client:
        response = client.post("/documents", json={"title": PRIVATE, "content_markdown": PRIVATE})
        _error(response, 500, "storage_error", False)
    with pg_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM document_versions")).scalar_one() == 0


def test_database_operational_errors_are_safe_retryable_503(pg_engine, world):
    with _client(pg_engine, world["user"], world["project"]) as client:
        saved = _create(client)

        def fail_operation(*args, **kwargs):
            raise OperationalError(PRIVATE, {"private": PRIVATE}, Exception(PRIVATE))

        event.listen(pg_engine, "before_cursor_execute", fail_operation)
        try:
            responses = [
                client.get("/documents"),
                client.get(_version_path(saved)),
                client.post("/documents", json={"title": PRIVATE, "content_markdown": PRIVATE}),
            ]
            for response in responses:
                _error(response, 503, "storage_unavailable", True)
        finally:
            event.remove(pg_engine, "before_cursor_execute", fail_operation)
