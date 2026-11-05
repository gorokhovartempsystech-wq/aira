"""Schema size boundaries and a downgrade racing an uncommitted writer."""

import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.test_docx_checkpoint_migrations import (
    TABLE,
    V8,
    V9,
    downgrade,
    insert,
    row,
    seed_v8,
)
from tests.acceptance.test_docx_storage_transactions import observe_backend, wait_for_lock


@pytest.fixture
def parent(empty_pg_engine, apply_migrations):
    apply_migrations(empty_pg_engine, V8)
    document_id = seed_v8(empty_pg_engine)
    apply_migrations(empty_pg_engine, V9)
    return empty_pg_engine, document_id


@pytest.mark.parametrize("phase", ["empty", "working", "pending"])
def test_valid_phase_and_tombstone_roundtrip_without_cascade(parent, phase):
    engine, document_id = parent
    with engine.begin() as conn:
        insert(conn, row(document_id, phase))
        assert conn.scalar(text(f"SELECT phase FROM {TABLE}")) == phase
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            insert(conn, row(document_id, phase))
        assert caught.value.orig.sqlstate == "23505"
        conn.execute(
            text("DELETE FROM docx_edit_drafts WHERE document_id=:id"), {"id": document_id}
        )
        conn.execute(
            text("DELETE FROM docx_edit_receipts WHERE document_id=:id"), {"id": document_id}
        )
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            conn.execute(text("DELETE FROM docx_documents WHERE id=:id"), {"id": document_id})
        assert caught.value.orig.sqlstate == "23503"
        conn.execute(
            text(f"""
            UPDATE {TABLE} SET phase='empty',checkpoint_revision=checkpoint_revision+1,
            base_storage_revision=NULL,base_sha256=NULL,working_data=NULL,
            working_sha256=NULL,metadata=NULL,last_request_id=:r,last_request_sha256=:h
        """),
            {"r": uuid4(), "h": "b" * 64},
        )
        assert conn.scalar(text(f"SELECT checkpoint_revision FROM {TABLE}")) == 2


@pytest.mark.parametrize(
    "phase,overrides",
    [
        ("empty", {"base_storage_revision": 2}),
        ("empty", {"working_data": b"x"}),
        ("empty", {"metadata": {"pending": None}}),
        ("pending", {"metadata": {}}),
        ("pending", {"metadata": {"pending": None}}),
        ("pending", {"metadata": {"pending": []}}),
    ],
)
def test_cross_phase_unknown_nulls_are_rejected(pg_engine, phase, overrides):
    with pg_engine.begin() as conn:
        values = row(uuid4(), phase, **overrides)
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            insert(conn, values)
        assert caught.value.orig.sqlstate == "23514"


def test_foreign_document_is_rejected(pg_engine):
    with pg_engine.begin() as conn:
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            insert(conn, row(uuid4()))
        assert caught.value.orig.sqlstate == "23503"


def test_max_archive_bytes_are_inclusive_and_overflow_rolls_back(parent):
    engine, document_id = parent
    with engine.begin() as conn:
        insert(conn, row(document_id, "working", working_data=b"x" * 33554432))
        assert conn.scalar(text(f"SELECT octet_length(working_data) FROM {TABLE}")) == 33554432
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            conn.execute(text(f"UPDATE {TABLE} SET working_data=:data"), {"data": b"x" * 33554433})
        assert caught.value.orig.sqlstate == "23514"
        assert conn.scalar(text(f"SELECT octet_length(working_data) FROM {TABLE}")) == 33554432


def test_metadata_byte_boundary_and_update_failure_keep_original(parent):
    engine, document_id = parent
    metadata = {"pending": None, "padding": ""}
    metadata["padding"] = "x" * (65536 - len(json.dumps(metadata).encode()))
    with engine.begin() as conn:
        insert(conn, row(document_id, "working", metadata=metadata))
        assert conn.scalar(text(f"SELECT octet_length(metadata::text) FROM {TABLE}")) == 65536
        metadata["padding"] += "x"
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            conn.execute(
                text(f"UPDATE {TABLE} SET metadata=CAST(:value AS jsonb)"),
                {"value": json.dumps(metadata)},
            )
        assert caught.value.orig.sqlstate == "23514"
        assert conn.scalar(text(f"SELECT octet_length(metadata::text) FROM {TABLE}")) == 65536


def test_downgrade_waits_for_writer_and_then_preserves_its_unsaved_work(parent):
    engine, document_id = parent
    # An uncommitted INSERT is invisible to the downgrade's initial snapshot.
    # Lock-before-inspect must wait, then see it; check-before-DROP would lose it.
    with ThreadPoolExecutor(max_workers=1) as pool:
        with engine.connect() as writer:
            tx = writer.begin()
            try:
                insert(writer, row(document_id, "working"))
                with observe_backend(engine) as (started, backend):
                    future = pool.submit(downgrade, engine)
                    wait_for_lock(engine, started, backend)
                    tx.commit()
                    with pytest.raises(RuntimeError):
                        future.result(timeout=10)
            finally:
                if tx.is_active:
                    tx.rollback()
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V9
        assert conn.scalar(text(f"SELECT phase FROM {TABLE}")) == "working"
