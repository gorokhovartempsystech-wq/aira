"""Independent PostgreSQL gate using only newly created disposable databases."""

import hashlib
import os
import pwd
import uuid
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def empty_pg_engine():
    fingerprint = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
    socket_dir = f"/private/tmp/ara-pg-{os.getuid()}-{fingerprint}"
    username = pwd.getpwuid(os.getuid()).pw_name
    database = "ara_check_" + uuid.uuid4().hex
    try:
        admin = psycopg.connect(
            host=socket_dir,
            port=5432,
            user=username,
            dbname="postgres",
            connect_timeout=5,
            autocommit=True,
        )
    except psycopg.OperationalError:
        pytest.fail(
            "Local PostgreSQL unavailable: start it with bash scripts/postgres.sh start "
            "or request normal sandbox approval for its Unix socket"
        )
    with admin:
        actual_data = admin.execute("SHOW data_directory").fetchone()[0]
        expected_data = Path(
            os.environ.get("ARA_TEST_PG_DATA_DIR", str(ROOT / ".runtime/postgres18/data"))
        )
        assert expected_data.is_absolute()
        assert Path(actual_data).resolve() == expected_data.resolve()
        assert admin.execute("SHOW listen_addresses").fetchone() == ("",)
        # Cleanup is enabled only after CREATE succeeds; never adopt an existing database.
        admin.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
        )
        engine = None
        try:
            engine = create_engine(
                URL.create(
                    "postgresql+psycopg",
                    username=username,
                    database=database,
                    query={"host": socket_dir, "connect_timeout": "5"},
                ),
                poolclass=NullPool,
                hide_parameters=True,
            )
            yield engine
        finally:
            if engine is not None:
                engine.dispose()
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


@pytest.fixture
def apply_migrations():
    def apply(engine, revision="head"):
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            if revision == "base":
                command.downgrade(config, revision)
            else:
                command.upgrade(config, revision)

    return apply


@pytest.fixture
def pg_engine(empty_pg_engine, apply_migrations):
    apply_migrations(empty_pg_engine)
    return empty_pg_engine


@pytest.fixture
def run_world(pg_engine, monkeypatch):
    """Synthetic HTTP clients/documents shared by the independent run acceptance."""
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from ara.app import create_app
    from ara.documents.runtime import DocumentRuntime

    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    owners = {name: uuid.uuid4() for name in ("own", "foreign")}
    projects = {name: uuid.uuid4() for name in ("own", "peer", "foreign")}
    with pg_engine.begin() as connection:
        for owner in owners.values():
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": owner})
        for scope, project in projects.items():
            connection.execute(
                text("INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, 'Synthetic')"),
                {"id": project, "owner": owners["foreign" if scope == "foreign" else "own"]},
            )
    runtimes = {
        scope: DocumentRuntime(
            engine=pg_engine,
            user_id=owners["foreign" if scope == "foreign" else "own"],
            project_id=project,
            mode="local",
        )
        for scope, project in projects.items()
    }

    def client(scope="own", *, engine=None):
        runtime = runtimes[scope] if engine is None else replace(runtimes[scope], engine=engine)
        return TestClient(create_app(document_runtime=runtime), raise_server_exceptions=False)

    documents = {}
    for name, scope in (
        ("own", "own"),
        ("second", "own"),
        ("peer", "peer"),
        ("foreign", "foreign"),
    ):
        with client(scope) as http:
            response = http.post(
                "/documents",
                json={
                    "title": "Synthetic document",
                    "content_markdown": "# Device\r\n\r\nOriginal  text\r\n",
                },
            )
            assert response.status_code == 201
            documents[name] = response.json()
    return {
        "engine": pg_engine,
        "owners": owners,
        "projects": projects,
        "runtimes": runtimes,
        "client": client,
        "documents": documents,
        "body": {
            "mode": "merge",
            "base_version_id": documents["own"]["current_version_id"],
            "context_items": [
                {
                    "id": "req-1",
                    "role": "new_requirement",
                    "text": "  Preserve the device name.\r\n",
                }
            ],
        },
    }


@pytest.fixture
def review_world(run_world):
    """Synthetic succeeded runs with editable, blocked and alternative change groups."""
    from copy import deepcopy

    from ara.worker import claim_next, complete_attempt, fixture_result

    world = {**run_world, "runs": {}, "run_bodies": {}}
    for name, scope in (
        ("own", "own"),
        ("second", "own"),
        ("peer", "peer"),
        ("foreign", "foreign"),
    ):
        body = deepcopy(world["body"])
        body["base_version_id"] = world["documents"][name]["current_version_id"]
        with world["client"](scope) as client:
            created = client.post(
                f"/documents/{world['documents'][name]['id']}/runs",
                json=body,
                headers={"Idempotency-Key": "review-fixture-" + name},
            )
            assert created.status_code == 202, created.text
        claim = claim_next(world["engine"])
        assert str(claim.run_id) == created.json()["run_id"]
        result = fixture_result(claim.request)
        target = claim.request.base_document.blocks[-1]
        context = claim.request.context.items[0]
        evidence = [{"source": "context", "id": context.id, "quote": context.text}]

        def group(group_id, operation, new_blocks, *, dependencies=(), questions=()):
            return {
                "id": group_id,
                "title": "Synthetic " + group_id,
                "basis": "explicit_requirement",
                "rationale": "Synthetic review scenario",
                "evidence": deepcopy(evidence),
                "depends_on_group_ids": list(dependencies),
                "blocking_question_ids": list(questions),
                "patches": [
                    {
                        "operation": operation,
                        "target_block_id": target.id,
                        "new_blocks": new_blocks,
                    }
                ],
            }

        result["change_groups"] = [
            group(
                "g1",
                "replace_block",
                [
                    {"kind": "paragraph", "text": "  First proposal\r\n"},
                    {"kind": "code", "text": '```json\n{"synthetic": true}\n```\n'},
                ],
            ),
            group(
                "g2",
                "insert_after",
                [{"kind": "paragraph", "text": "Blocked proposal\n"}],
                dependencies=("g1",),
                questions=("q1",),
            ),
            group("g3", "delete_block", []),
        ]
        result["review_status"] = "needs_clarification"
        result["questions"] = [
            {
                "id": "q1",
                "prompt": "Clarify the synthetic requested behavior?",
                "reason": "A review must not silently answer this question.",
                "evidence": deepcopy(evidence),
            }
        ]
        result["change_outcomes"] = [
            {
                "context_item_id": context.id,
                "status": "proposed",
                "rationale": "Synthetic alternatives and a blocked group",
                "change_group_ids": ["g1", "g2", "g3"],
                "question_ids": ["q1"],
                "evidence": deepcopy(evidence),
            }
        ]
        assert complete_attempt(world["engine"], claim, result)
        with world["client"](scope) as client:
            saved = client.get(f"/runs/{claim.run_id}")
            assert saved.status_code == 200
            world["runs"][name] = saved.json()
            world["run_bodies"][name] = body
    return world
