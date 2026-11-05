"""B2A ORM DDL parity, inert imports and scoped counter/retry edges."""

import subprocess
import sys

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.test_docx_analysis_storage_migrations import (
    TABLES,
    R,
    S,
    insert,
    parents,
    put,
    records,
)


def test_orm_generated_checks_and_deferred_fks_match_migration(pg_engine):
    from ara.db import Base

    with pg_engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA b2a_orm")
        conn.exec_driver_sql("SET LOCAL search_path TO b2a_orm")
        Base.metadata.create_all(conn)
        inspector = inspect(conn)
        for table in TABLES:
            for method in (
                inspector.get_check_constraints,
                inspector.get_unique_constraints,
                inspector.get_foreign_keys,
                inspector.get_indexes,
            ):

                def shape(schema):
                    rows = method(table, schema=schema)
                    return sorted(
                        ({k: v for k, v in r.items() if k != "referred_schema"} for r in rows),
                        key=lambda r: r["name"],
                    )

                assert shape("public") == shape("b2a_orm"), (table, method.__name__)


def test_bigint_max_and_overflow_do_not_wrap(pg_engine):
    with pg_engine.begin() as conn:
        scope = parents(conn)
        r, a, x = records(scope)
        r.update(storage_revision=2**63 - 1, accepted_order=2**63 - 1)
        put(conn, (r, a, x))
        for key in ("storage_revision", "accepted_order"):
            with pytest.raises(DBAPIError) as caught, conn.begin_nested():
                conn.execute(text(f"UPDATE {R} SET {key}=:v"), {"v": 2**63})
            assert caught.value.orig.sqlstate == "22003"
        assert conn.scalar(text(f"SELECT accepted_order FROM {R}")) == 2**63 - 1


@pytest.mark.parametrize("self_reference", [False, True])
def test_retry_parent_scope_and_self_reference(pg_engine, self_reference):
    with pg_engine.begin() as conn:
        scope = parents(conn)
        original = records(parents(conn), "failed")
        put(conn, original)
        r = records(scope)[0]
        r.update(
            start_kind="retry", retry_of_run_id=r["id"] if self_reference else original[0]["id"]
        )
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            insert(conn, R, r)
        assert caught.value.orig.sqlstate == ("23514" if self_reference else "23503")


def test_binary_storage_does_not_coerce_utf8_or_nul(pg_engine):
    with pg_engine.begin() as conn:
        scope = parents(conn)
        conn.execute(text(f"UPDATE {S} SET source_data=:v"), {"v": b"\x00\xff"})
        assert (
            conn.scalar(
                text(f"SELECT source_data FROM {S} WHERE document_id=:id"), {"id": scope[0]}
            )
            == b"\x00\xff"
        )
        # Package/UTF-8 validation belongs to B2B; this is deliberately BYTEA.


def test_fresh_model_and_migration_imports_have_no_runtime_io():
    from tests.acceptance.conftest import ROOT

    program = """
import os, pathlib, runpy, sys
import alembic.op, sqlalchemy, sqlalchemy.orm, dotenv
from sqlalchemy.dialects import postgresql
def forbidden(*a, **k): raise AssertionError('Unexpected runtime I/O')
sqlalchemy.create_engine = forbidden
dotenv.load_dotenv = forbidden
pathlib.Path.home = forbidden
def audit(event, args):
    if event in ('socket.connect','subprocess.Popen','os.system'):
        forbidden()
    if event == 'open' and isinstance(args[0],str) and (
        args[0].endswith('secrets.env') or '/.runtime/' in args[0]):
        forbidden()
sys.addaudithook(audit)
import ara.models
runpy.run_path(sys.argv[1])
print('inert')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(ROOT / "migrations/versions/0010_docx_analysis_storage.py"),
        ],
        cwd=ROOT / "src",
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert result.stdout.strip() == "inert"
    assert not result.stderr
