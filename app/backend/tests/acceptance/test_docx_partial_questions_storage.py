"""Explicit Docker-socket integration, with a newly created disposable database only."""

import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import URL, create_engine, text
from test_docx_analysis_runs_start import world
from test_docx_partial_questions import setup
from test_docx_review_v1 import canonical
from test_docx_structured_runtime import set_source
from test_docx_visible_word import source
from test_docx_word_runtime import start

from ara.docx_analysis.storage_codec import restore_source
from ara.docx_analysis_runs import lifecycle


@pytest.fixture
def disposable_database():
    socket = os.environ.get("AIRA_TEST_PG_SOCKET")
    if not socket:
        pytest.skip("Explicit disposable PostgreSQL socket required")
    name = "aira_partial_test_" + uuid4().hex
    with psycopg.connect(host=socket, user="postgres", dbname="postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        engine = create_engine(
            URL.create(
                "postgresql+psycopg", username="postgres", database=name, query={"host": socket}
            ),
            hide_parameters=True,
        )
        try:
            root = Path(__file__).resolve().parents[2]
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            yield engine
        finally:
            engine.dispose()
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.mark.parametrize("cancel", [False, True])
def test_partial_question_persisted_or_cancelled(disposable_database, cancel):
    w = world.__wrapped__(disposable_database)
    set_source(w, source("plain"))
    admitted = start(w)
    claim = lifecycle.claim_next(w["engine"], worker_instance_id=uuid4())
    assert claim.run_id == admitted.summary.run_id
    _, _, reply, _ = setup("plain", partial=True)
    f = restore_source(claim.source).snapshot.fragments[-1]
    reply["extensions"]["standalone_questions"][0]["references"] = [
        dict(fragment_id=f.fragment_id, start=0, end=len(f.text))
    ]
    if cancel:
        scope = w["scopes"]["own"]
        lifecycle.cancel_run(scope["runtime"], document_id=scope["doc"], run_id=claim.run_id)
    # Fixture construction is intentionally outside the worker lease budget.
    if not cancel:
        assert lifecycle.heartbeat(w["engine"], claim, stage="analyzing").accepted
    result = lifecycle.complete_attempt(w["engine"], claim, reply=canonical(reply))
    assert result.accepted is (not cancel)
    with w["engine"].connect() as conn:
        rows = conn.execute(
            text(
                "SELECT result_data, questions_count, no_findings "
                "FROM docx_analysis_results WHERE run_id=:id"
            ),
            {"id": claim.run_id},
        ).all()
    if cancel:
        assert rows == []
    else:
        assert len(rows) == 1
        body = json.loads(bytes(rows[0].result_data))
        assert rows[0].questions_count == 1 and not rows[0].no_findings
        assert body["analysis_coverage"]["state"] == "partial"
        assert body["standalone_questions"][0]["evidence"][0]["slices"]
        assert result.state.summary.status == "succeeded"
        from ara.docx_review_api._view import get_review

        scope = w["scopes"]["own"]
        reopened = get_review(scope["runtime"], scope["doc"], claim.run_id)
        assert reopened["matches_saved_document"]
        assert reopened["view"]["standalone_questions"] == body["standalone_questions"]
        assert reopened["view"]["analysis_coverage"]["state"] == "partial"
        assert not reopened["view"]["no_findings"]
