"""Settings and imports stay safe before an explicit database connection."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text


def test_settings_are_explicit_and_secrets_are_redacted(tmp_path, monkeypatch):
    from ara.config import ConfigurationError, DatabaseSettings, load_settings

    # Synthetic test data only; the real user's secrets file is never touched.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    secret_file = tmp_path / "secrets.env"
    secret_file.write_text("ARA_DATABASE_URL=postgresql+psycopg://test:synthetic-marker@db/ara\n")
    original = os.environ.get("ARA_DATABASE_URL")
    settings = load_settings(environ={})
    assert "synthetic-marker" in settings.database_url.get_secret_value()
    assert "synthetic-marker" not in repr(settings)
    assert "synthetic-marker" not in str(settings)
    assert os.environ.get("ARA_DATABASE_URL") == original

    public_url = "postgresql+psycopg://test@db/override"
    assert (
        load_settings(environ={"ARA_DATABASE_URL": public_url}).database_url.get_secret_value()
        == public_url
    )
    with pytest.raises(ConfigurationError):
        load_settings(environ={"ARA_DATABASE_URL": ""})
    secret_file.unlink()
    with pytest.raises(ConfigurationError) as missing:
        load_settings(environ={})
    assert "ARA_DATABASE_URL" in str(missing.value)
    for invalid in ("", "not-a-url:synthetic-marker", "sqlite:///synthetic-marker.db"):
        with pytest.raises(ConfigurationError) as error:
            DatabaseSettings(database_url=invalid)
        assert "synthetic-marker" not in str(error.value)
        assert "synthetic-marker" not in repr(error.value)


def test_new_modules_do_not_load_config_or_connect_at_import(tmp_path):
    source_root = Path(__file__).resolve().parents[2] / "src"
    script = """
import sys
import dotenv
import psycopg
import sqlalchemy
import pydantic_settings

def forbidden(*args, **kwargs):
    raise AssertionError('Import must not load settings or create database engines/connections')

dotenv.load_dotenv = forbidden
dotenv.dotenv_values = forbidden
psycopg.connect = forbidden
sqlalchemy.create_engine = forbidden
sys.path.insert(0, sys.argv[1])

def guard(event, args):
    if event == 'open' and str(args[0]).endswith(('secrets.env', '.env')):
        forbidden()
    if event.startswith('socket.'):
        forbidden()

sys.addaudithook(guard)
import ara.config
import ara.db
import ara.models
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(source_root)],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_engine_is_lazy_then_connects_to_real_postgres(empty_pg_engine):
    from ara.config import DatabaseSettings
    from ara.db import create_database_engine

    settings = DatabaseSettings(
        database_url=empty_pg_engine.url.render_as_string(hide_password=False)
    )
    with patch(
        "psycopg.connect", side_effect=AssertionError("Engine creation opened a connection")
    ):
        engine = create_database_engine(settings)
    try:
        assert engine.echo is False
        assert engine.hide_parameters is True
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT current_database()")) == empty_pg_engine.url.database
            )
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()
