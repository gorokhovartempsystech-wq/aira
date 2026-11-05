"""Acceptance gate owned by the reviewer, outside Ralph's application scope."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_application_factory_and_health_contract():
    from ara.app import create_app

    app = create_app()
    assert isinstance(app, FastAPI)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


def test_factory_creates_independent_apps_without_database_configuration(monkeypatch):
    monkeypatch.delenv("ARA_DATABASE_URL", raising=False)
    from ara.app import create_app

    first = create_app()
    second = create_app()
    assert first is not second
    with TestClient(first) as client:
        assert client.get("/health").status_code == 200
