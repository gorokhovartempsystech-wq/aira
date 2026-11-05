"""Independent server identity and local-only launch acceptance."""

import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from ara.app import create_app
from ara.config import ConfigurationError
from ara.documents.runtime import DocumentRuntime


def runtime_for(engine, user_id, project_id):
    return DocumentRuntime(engine=engine, user_id=user_id, project_id=project_id, mode="local")


@pytest.fixture
def identities(pg_engine, monkeypatch):
    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    owners = [(uuid4(), uuid4()), (uuid4(), uuid4())]
    with pg_engine.begin() as connection:
        for user_id, project_id in owners:
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": user_id})
            connection.execute(
                text("INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, 'Synthetic')"),
                {"id": project_id, "owner": user_id},
            )
    return owners


def test_me_uses_checked_server_identity_and_ignores_http_spoof(pg_engine, identities):
    for index, (user_id, project_id) in enumerate(identities):
        foreign_user, foreign_project = identities[1 - index]
        app = create_app(document_runtime=runtime_for(pg_engine, user_id, project_id))
        with TestClient(app) as client:
            response = client.get(
                "/me",
                params={"user_id": str(foreign_user), "project_id": str(foreign_project)},
                headers={
                    "X-User-ID": str(foreign_user),
                    "X-Project-ID": str(foreign_project),
                    "X-ARA-Auth-Mode": "real-session",
                },
            )
        assert response.status_code == 200
        assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
        assert response.json() == {
            "user_id": str(user_id),
            "project_id": str(project_id),
            "environment": "local",
            "auth_mode": "local-dev",
        }


def test_me_checks_owner_and_missing_project_without_disclosure(pg_engine, identities):
    owner, project = identities[0]
    foreign_owner, _ = identities[1]
    errors = []
    for user_id, project_id in ((foreign_owner, project), (owner, uuid4()), (uuid4(), project)):
        app = create_app(document_runtime=runtime_for(pg_engine, user_id, project_id))
        with TestClient(app) as client:
            response = client.get("/me", headers={"X-Request-ID": "client-controlled"})
        assert response.status_code == 404
        assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
        body = response.json()
        assert set(body) == {"code", "message", "retryable", "request_id"}
        assert body["code"] == "not_found" and body["retryable"] is False
        assert isinstance(body["message"], str) and body["message"]
        assert isinstance(body["request_id"], str) and body["request_id"]
        assert body.pop("request_id") != "client-controlled"
        assert str(owner) not in response.text and str(project) not in response.text
        errors.append(body)
    assert errors == [errors[0]] * len(errors)


def test_me_storage_failure_is_safe_retryable_503(pg_engine, identities, monkeypatch):
    sentinel = "SYNTHETIC_STORAGE_SECRET_912"

    def fail(*args, **kwargs):
        raise OperationalError(sentinel, {}, Exception(sentinel))

    user_id, project_id = identities[0]
    app = create_app(document_runtime=runtime_for(pg_engine, user_id, project_id))
    monkeypatch.setattr(pg_engine, "connect", fail)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/me")
    assert response.status_code == 503
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    body = response.json()
    assert set(body) == {"code", "message", "retryable", "request_id"}
    assert body["code"] == "storage_unavailable" and body["retryable"] is True
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["request_id"], str) and body["request_id"]
    assert sentinel not in response.text


@pytest.mark.parametrize("environment", ["pilot", "production", "", "LOCAL"])
def test_explicit_local_runtime_cannot_enable_http_in_nonlocal_environment(
    monkeypatch, environment
):
    def forbidden(*args, **kwargs):
        pytest.fail("Rejected local mode must not read secrets or connect")

    engine = create_engine("postgresql+psycopg://synthetic@localhost/unused")
    try:
        runtime = runtime_for(engine, uuid4(), uuid4())
        monkeypatch.setenv("ARA_ENVIRONMENT", environment)
        monkeypatch.setattr("ara.config.load_settings", forbidden)
        monkeypatch.setattr("ara.config.dotenv_values", forbidden)
        monkeypatch.setattr(engine, "connect", forbidden)
        with pytest.raises(ConfigurationError):
            create_app(document_runtime=runtime)
        # The independent health-only factory stays usable without a local identity.
        with TestClient(create_app()) as client:
            assert client.get("/health").json() == {"status": "ok"}
            assert client.get("/me").status_code == 404
    finally:
        engine.dispose()


def test_document_launcher_binds_only_loopback_and_rejects_pilot(monkeypatch):
    import uvicorn

    path = Path(__file__).resolve().parents[2] / "scripts/serve_documents.py"
    spec = importlib.util.spec_from_file_location("test_document_launcher", path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setenv("ARA_ENVIRONMENT", "local")
    monkeypatch.setenv("ARA_PORT", "8019")
    monkeypatch.setenv("ARA_HOST", "0.0.0.0")
    monkeypatch.setenv("ARA_DATABASE_URL", "ignored-synthetic-value")
    launcher.main()
    assert calls == [
        (("ara.local:create_local_app",), {"factory": True, "host": "127.0.0.1", "port": 8019})
    ]
    monkeypatch.setenv("ARA_ENVIRONMENT", "pilot")
    with pytest.raises(SystemExit):
        launcher.main()
    assert len(calls) == 1
