"""Exercise the standalone migration command against an isolated real PostgreSQL."""

import hashlib
import os
import pwd
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from psycopg import sql
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import StatementError

from ara import models  # noqa: F401
from ara.config import DatabaseSettings
from ara.db import Base, create_database_engine

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def isolated_database():
    fingerprint = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
    host = f"/private/tmp/ara-pg-{os.getuid()}-{fingerprint}"
    user = pwd.getpwuid(os.getuid()).pw_name
    database = "ara_check_" + uuid.uuid4().hex
    with psycopg.connect(
        host=host, user=user, dbname="postgres", port=5432, connect_timeout=5, autocommit=True
    ) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            yield URL.create(
                "postgresql+psycopg",
                username=user,
                database=database,
                query={"host": host, "connect_timeout": "5"},
            ).render_as_string(hide_password=False)
        finally:
            # Only this fixture's freshly generated database may be removed.
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def test_explicit_cli_upgrade_repeat_downgrade_and_redaction(isolated_database, tmp_path):
    def migrate(*arguments):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *arguments],
            cwd=tmp_path,
            env={"ARA_DATABASE_URL": isolated_database},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

    engine = create_database_engine(DatabaseSettings(database_url=isolated_database))
    try:
        migrate("upgrade", "head")
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            first_tables = inspect(connection).get_table_names()
        migrate("upgrade", "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
            assert inspect(connection).get_table_names() == first_tables
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            with pytest.raises(StatementError) as caught:
                connection.execute(
                    text("SELECT CAST(:value AS uuid)"), {"value": "private parameter"}
                )
            # The SQLAlchemy parameter dump must be suppressed even on failure.
            assert "[parameters:" not in str(caught.value)
            assert "SQL parameters hidden" in str(caught.value)
        migrate("downgrade", "base")
        with engine.connect() as connection:
            assert inspect(connection).get_table_names() == ["alembic_version"]
        migrate("upgrade", "head")
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    finally:
        engine.dispose()
