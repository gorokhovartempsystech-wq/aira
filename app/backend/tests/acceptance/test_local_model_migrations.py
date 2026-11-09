"""Local review migrations preserve existing DOCX data and refuse result loss."""

import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT
from sqlalchemy import inspect, text
from test_docx_checkpoint_migrations import V9, seed_v8

V10 = "0010_local_model_reviews"


def downgrade(engine):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, V9)


def test_local_review_migration_preserves_document_and_refuses_data_loss(
    empty_pg_engine, apply_migrations
):
    engine = empty_pg_engine
    apply_migrations(engine, V9)
    document_id = seed_v8(engine)
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT * FROM docx_documents WHERE id=:id"), {"id": document_id}
        ).one()
    apply_migrations(engine, V10)
    downgrade(engine)
    with engine.connect() as conn:
        assert "local_model_reviews" not in inspect(conn).get_table_names()
        assert (
            conn.execute(
                text("SELECT * FROM docx_documents WHERE id=:id"), {"id": document_id}
            ).one()
            == before
        )
    apply_migrations(engine, V10)
    identity = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO local_model_reviews "
                "(id,document_id,revision,source_sha256,result) "
                "VALUES (:id,:doc,2,:sha,CAST(:result AS jsonb))"
            ),
            {
                "id": identity,
                "doc": document_id,
                "sha": "a" * 64,
                "result": json.dumps({"synthetic": True}),
            },
        )
    with pytest.raises(RuntimeError, match="stored review"):
        downgrade(engine)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V10
        assert conn.scalar(
            text("SELECT result FROM local_model_reviews WHERE id=:id"), {"id": identity}
        ) == {"synthetic": True}
