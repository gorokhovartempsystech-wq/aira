"""Behavior of the initial application, independent of database configuration."""

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from ara.app import create_app


def test_health_returns_exact_public_contract():
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_app_instances_do_not_share_runtime_state(monkeypatch):
    monkeypatch.delenv("ARA_DATABASE_URL", raising=False)
    first = create_app()
    second = create_app()
    first.state.instance_label = "first"

    assert first is not second
    assert not hasattr(second.state, "instance_label")
    with TestClient(second) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_fresh_import_and_factory_without_configuration_or_external_io(tmp_path):
    source_root = Path(__file__).resolve().parents[2] / "src"
    # A fresh interpreter exercises import-time code even if other tests imported ara.
    # Initialize the framework first (it reads OS metadata on macOS), then guard ara.
    # Python module reads remain allowed so the application can be imported normally.
    script = """
import sys
from fastapi import FastAPI

sys.path.insert(0, sys.argv[1])

def guard(event, args):
    if event == "open":
        path = args[0]
        if not isinstance(path, str) or not path.endswith((".py", ".pyc", ".so", ".pyd")):
            raise AssertionError("Application import or construction attempted file access")
    if event.startswith("socket."):
        raise AssertionError("Application import or construction attempted network access")
    if event == "import" and args[0].split(".")[0] in {"psycopg", "sqlalchemy", "sqlite3"}:
        raise AssertionError("Health-only application must not initialize database libraries")

sys.addaudithook(guard)
from ara.app import create_app

assert isinstance(create_app(), FastAPI)
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
