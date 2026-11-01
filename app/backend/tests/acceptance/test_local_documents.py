"""Independent local-mode startup gate; all records are synthetic."""

import importlib
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

LOCAL_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
LOCAL_PROJECT_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")


def forbidden(*args, **kwargs):
    raise AssertionError("Unexpected settings read, connection, or migration")


def configure_local(monkeypatch, engine):
    monkeypatch.setenv("ARA_ENVIRONMENT", "local")
    monkeypatch.setenv("ARA_DATABASE_URL", engine.url.render_as_string(hide_password=False))


def test_document_runtime_is_explicit_immutable_and_does_not_connect(monkeypatch):
    from ara.config import ConfigurationError

    DocumentRuntime = importlib.import_module("ara.documents.runtime").DocumentRuntime

    engine = create_engine("postgresql+psycopg://synthetic@localhost/unused")
    try:
        monkeypatch.setattr(engine, "connect", forbidden)
        monkeypatch.setattr(engine, "raw_connection", forbidden)
        monkeypatch.setattr("ara.config.load_settings", forbidden)
        monkeypatch.setattr("ara.config.dotenv_values", forbidden)
        runtime = DocumentRuntime(
            engine=engine, user_id=LOCAL_USER_ID, project_id=LOCAL_PROJECT_ID, mode="local"
        )
        assert runtime.engine is engine
        assert runtime.user_id == LOCAL_USER_ID
        assert runtime.project_id == LOCAL_PROJECT_ID
        assert runtime.mode == "local"
        for field, value in (
            ("engine", None),
            ("user_id", uuid.uuid4()),
            ("project_id", uuid.uuid4()),
            ("mode", "pilot"),
        ):
            with pytest.raises((AttributeError, TypeError)):
                setattr(runtime, field, value)
        for mode in (None, "", "pilot", "production"):
            with pytest.raises(ConfigurationError):
                DocumentRuntime(
                    engine=engine, user_id=LOCAL_USER_ID, project_id=LOCAL_PROJECT_ID, mode=mode
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", [None, "", "pilot", "production", "LOCAL"])
def test_nonlocal_startup_rejected_before_settings_or_database(monkeypatch, mode):
    from ara import config, db

    if mode is None:
        monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("ARA_ENVIRONMENT", mode)
    monkeypatch.setattr(config, "load_settings", forbidden)
    monkeypatch.setattr(config, "dotenv_values", forbidden)
    monkeypatch.setattr(db, "create_database_engine", forbidden)
    local = importlib.reload(importlib.import_module("ara.local"))
    with pytest.raises(config.ConfigurationError):
        local.create_local_app()


def test_local_module_import_is_inert(tmp_path):
    source_root = Path(__file__).resolve().parents[2] / "src"
    script = """
import sys
import dotenv
import fastapi
import psycopg
import sqlalchemy
sys.path.insert(0, sys.argv[1])
import ara.config
import ara.db

def forbidden(*args, **kwargs):
    raise AssertionError('Local module import must be inert')

ara.config.load_settings = forbidden
ara.config.dotenv_values = forbidden
ara.db.create_database_engine = forbidden
dotenv.dotenv_values = forbidden
dotenv.load_dotenv = forbidden
sqlalchemy.create_engine = forbidden
psycopg.connect = forbidden

def guard(event, args):
    if event == 'open' and str(args[0]).endswith(('secrets.env', '.env')):
        forbidden()
    if event.startswith('socket.'):
        forbidden()

sys.addaudithook(guard)
import ara.local
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(source_root)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_local_startup_provisions_once_and_disposes_owned_engine(pg_engine, monkeypatch):
    from ara import db
    from ara.models import Project, User

    configure_local(monkeypatch, pg_engine)
    original_create_engine = db.create_database_engine
    owned_engines = []

    def track_engine(settings):
        engine = original_create_engine(settings)
        owned_engines.append(engine)
        return engine

    monkeypatch.setattr(db, "create_database_engine", track_engine)
    local = importlib.reload(importlib.import_module("ara.local"))
    for _ in range(2):
        with patch("sqlalchemy.engine.Engine.connect", forbidden):
            app = local.create_local_app()
        assert len(owned_engines) > 0
        engine = owned_engines[-1]
        with patch.object(engine, "dispose", wraps=engine.dispose) as dispose:
            with TestClient(app) as client:
                assert client.get("/health").json() == {"status": "ok"}
                assert client.get("/documents").json() == {"items": []}
            assert dispose.call_count >= 1
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.get(User, LOCAL_USER_ID) is not None
        project = session.get(Project, LOCAL_PROJECT_ID)
        assert project.owner_id == LOCAL_USER_ID
        assert project.name == "Local development"


def test_local_startup_does_not_reassign_an_existing_project(pg_engine, monkeypatch):
    from ara.config import ConfigurationError
    from ara.models import Project, User

    other_owner = uuid.uuid4()
    with Session(pg_engine) as session, session.begin():
        session.add_all([User(id=LOCAL_USER_ID), User(id=other_owner)])
        session.flush()
        session.add(Project(id=LOCAL_PROJECT_ID, owner_id=other_owner, name="Synthetic private"))
    configure_local(monkeypatch, pg_engine)
    local = importlib.reload(importlib.import_module("ara.local"))
    with pytest.raises(ConfigurationError) as error:
        with TestClient(local.create_local_app()):
            pytest.fail("Conflicting project ownership must stop startup")
    assert "Synthetic private" not in str(error.value)
    with Session(pg_engine) as session:
        project = session.get(Project, LOCAL_PROJECT_ID)
        assert project.owner_id == other_owner
        assert project.name == "Synthetic private"
        assert session.scalar(select(func.count()).select_from(Project)) == 1


def test_local_startup_does_not_apply_migrations(empty_pg_engine, monkeypatch):
    configure_local(monkeypatch, empty_pg_engine)
    local = importlib.reload(importlib.import_module("ara.local"))
    with patch("sqlalchemy.engine.Engine.connect", forbidden):
        app = local.create_local_app()
    with pytest.raises(Exception):
        with TestClient(app):
            pytest.fail("An empty database requires an explicit migration before startup")
    assert inspect(empty_pg_engine).get_table_names() == []
