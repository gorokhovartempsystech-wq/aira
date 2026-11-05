"""Explicit operator configuration, inert construction and redacted CLI output."""

import importlib
import secrets
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import URL, event
from test_licensing_policy import synthetic_key
from test_licensing_server import api, reject


def settings_values(url=None, *, issue=False):
    password = secrets.token_urlsafe(24)
    values = {
        "AIRA_LICENSE_DATABASE_URL": url
        or URL.create(
            "postgresql+psycopg",
            username="synthetic",
            password=password,
            host="localhost",
            database="licenses",
        ).render_as_string(hide_password=False),
        "AIRA_LICENSE_PEPPER": secrets.token_hex(32),
    }
    if issue:
        values["AIRA_LICENSE_ISSUE_KEY"] = synthetic_key()
    return values


def test_explicit_settings_are_redacted_and_factory_does_not_connect():
    a = api()
    values = settings_values(issue=True)
    settings = a.load_settings(values=values)
    assert settings.issue_key is None
    issued = a.load_settings(values=values, for_issue=True)
    assert issued.issue_key == values["AIRA_LICENSE_ISSUE_KEY"]
    assert settings.pepper == bytes.fromhex(values["AIRA_LICENSE_PEPPER"])
    assert all(secret not in repr(settings) + repr(issued) for secret in values.values())
    runtime = a.create_runtime(settings)
    try:

        def forbidden(*args):
            raise AssertionError("factory attempted a connection")

        event.listen(runtime.engine, "connect", forbidden)
        application = a.create_license_app(runtime)
        assert len(application.routes) == 2
        assert runtime.engine.pool.size() == 2
        assert runtime.engine.pool._max_overflow == 0 and runtime.engine.pool.timeout() == 0.5
        assert runtime.engine.hide_parameters
    finally:
        runtime.engine.dispose()


@pytest.mark.parametrize(
    "name,value",
    [
        ("AIRA_LICENSE_DATABASE_URL", "sqlite:///private"),
        ("AIRA_LICENSE_DATABASE_URL", "SYNTHETIC_PRIVATE"),
        ("AIRA_LICENSE_PEPPER", ""),
        ("AIRA_LICENSE_PEPPER", "SYNTHETIC_PRIVATE"),
        ("AIRA_LICENSE_PEPPER", "ab" * 31),
    ],
)
def test_bad_settings_never_echo_values(name, value):
    values = settings_values() | {name: value}
    reject("validation_error", lambda: api().load_settings(values=values))
    values = settings_values()
    del values[name]
    reject("validation_error", lambda: api().load_settings(values=values))


def test_secret_file_is_only_read_explicitly_from_fixed_home_path(monkeypatch):
    a = api()
    module = importlib.import_module("ara.licensing.server._config")
    values = settings_values()
    calls = []

    def read(path, *, interpolate):
        calls.append((path, interpolate))
        return values

    monkeypatch.setattr(module, "dotenv_values", read)
    loaded = a.load_settings()
    assert calls == [(Path.home() / "secrets.env", False)]
    assert loaded.pepper == bytes.fromhex(values["AIRA_LICENSE_PEPPER"])
    calls.clear()
    a.load_settings(values=values)
    assert calls == []


def test_cli_issue_disable_enable_and_safe_failure(empty_pg_engine, monkeypatch, capsys):
    a = api()
    a.initialize_database(empty_pg_engine)
    module = importlib.import_module("ara.licensing.server.__main__")
    values = settings_values(empty_pg_engine.url.render_as_string(hide_password=False), issue=True)
    settings = a.load_settings(values=values, for_issue=True)
    requested = []

    def load(*, for_issue=False):
        requested.append(for_issue)
        return settings if for_issue else replace(settings, issue_key=None)

    monkeypatch.setattr(module, "load_settings", load)
    identity = uuid4()
    assert module.main(["issue", "--license-id", str(identity), "--duration-seconds", "3600"]) == 0
    assert module.main(["disable", "--license-id", str(identity)]) == 0
    runtime = a.ServerRuntime(empty_pg_engine, settings.pepper)
    assert not a.get_license(runtime, license_id=identity).enabled
    assert module.main(["enable", "--license-id", str(identity)]) == 0
    assert a.get_license(runtime, license_id=identity).enabled
    assert requested == [True, False, False]
    assert (
        module.main(
            ["issue", "--license-id", str(identity), "--duration-seconds", "SYNTHETIC_PRIVATE"]
        )
        == 2
    )
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "SYNTHETIC_PRIVATE" not in output
    assert values["AIRA_LICENSE_ISSUE_KEY"] not in output
    assert values["AIRA_LICENSE_PEPPER"] not in output
    assert values["AIRA_LICENSE_DATABASE_URL"] not in output


def test_cli_serve_has_explicit_loopback_proxy_boundary_and_no_auto_init(monkeypatch):
    a = api()
    module = importlib.import_module("ara.licensing.server.__main__")
    settings = a.load_settings(values=settings_values())
    monkeypatch.setattr(module, "load_settings", lambda **kwargs: settings)
    calls = []

    def serve(application, **kwargs):
        calls.append(kwargs)
        assert len(application.routes) == 2

    monkeypatch.setattr(module.uvicorn, "run", serve)
    assert module.main(["serve", "--port", "8766"]) == 0
    assert calls[0]["host"] == "127.0.0.1" and calls[0]["port"] == 8766
    assert calls[0]["forwarded_allow_ips"] == "127.0.0.1"
    assert calls[0]["proxy_headers"] is True and calls[0]["access_log"] is False
