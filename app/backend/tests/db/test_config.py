"""Settings are explicit, deterministic, and safe to report on failure."""

import traceback
from pathlib import Path

import pytest
from pydantic import SecretStr

from ara.config import ConfigurationError, DatabaseSettings, load_settings

VALID_URL = "postgresql+psycopg://synthetic:synthetic_password@localhost/example"


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "value",
    [
        "",
        "synthetic_password",
        "sqlite:///synthetic_password",
        "postgresql://u:synthetic_password@localhost/db",
        "postgresql+psycopg://u:synthetic_password@localhost",
        "postgresql+psycopg://u:synthetic_password@localhost:invalid/db",
        "postgresql+psycopg://u:synthetic_password@localhost:65536/db",
        " " + VALID_URL,
        None,
    ],
)
def test_invalid_urls_have_safe_errors(value):
    with pytest.raises(ConfigurationError) as caught:
        DatabaseSettings(database_url=value)
    rendered = "".join(traceback.format_exception(caught.value))
    assert "ARA_DATABASE_URL" in rendered
    assert "synthetic_password" not in rendered


def test_secretstr_and_frozen_settings():
    from dataclasses import FrozenInstanceError

    settings = DatabaseSettings(database_url=SecretStr(VALID_URL))
    assert settings.database_url.get_secret_value() == VALID_URL
    assert "synthetic_password" not in str(settings)
    assert "synthetic_password" not in repr(settings)
    with pytest.raises(FrozenInstanceError):
        settings.database_url = ""


def test_missing_and_empty_environment_override(fake_home):
    with pytest.raises(ConfigurationError, match="ARA_DATABASE_URL.*required"):
        load_settings(environ={})
    (fake_home / "secrets.env").write_text(f"ARA_DATABASE_URL='{VALID_URL}'\n")
    assert load_settings(environ={}).database_url.get_secret_value() == VALID_URL
    with pytest.raises(ConfigurationError, match="ARA_DATABASE_URL"):
        load_settings(environ={"ARA_DATABASE_URL": ""})


def test_environment_priority_does_not_read_files_or_mutate_environment(fake_home, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Environment configuration must not read a file")

    monkeypatch.setattr("ara.config.dotenv_values", forbidden)
    monkeypatch.setenv("ARA_DATABASE_URL", VALID_URL)
    assert load_settings().database_url.get_secret_value() == VALID_URL
    explicit = {"ARA_DATABASE_URL": "postgresql+psycopg:///different"}
    assert (
        load_settings(environ=explicit).database_url.get_secret_value()
        == explicit["ARA_DATABASE_URL"]
    )
    assert load_settings().database_url.get_secret_value() == VALID_URL


def test_file_loading_does_not_export_values(fake_home, monkeypatch):
    import os

    monkeypatch.delenv("ARA_DATABASE_URL", raising=False)
    (fake_home / "secrets.env").write_text(f"ARA_DATABASE_URL='{VALID_URL}'\n")
    assert load_settings().database_url.get_secret_value() == VALID_URL
    assert "ARA_DATABASE_URL" not in os.environ


def test_unreadable_file_has_safe_error(fake_home, monkeypatch):
    def unreadable(*args, **kwargs):
        raise OSError("synthetic_password")

    monkeypatch.setattr("ara.config.dotenv_values", unreadable)
    with pytest.raises(ConfigurationError) as caught:
        load_settings(environ={})
    assert "synthetic_password" not in "".join(traceback.format_exception(caught.value))
