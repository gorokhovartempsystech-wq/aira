"""Frozen D03-07 text history invariants and module delivery."""

import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ara.app import create_app
from ara.documents.runtime import DocumentRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "case",
    [
        "basic",
        "paste",
        "grouping",
        "deletion",
        "selection",
        "gap",
        "branch",
        "unicode",
        "capture",
        "unchanged",
        "recovered",
        "composition",
        "invalid",
        "capacity",
        "memory",
    ],
)
def test_history_invariants(case):
    bundled = Path(sys.base_prefix).parent / "node/bin/node"
    node = shutil.which("node") or (str(bundled) if bundled.is_file() else None)
    assert node is not None, "Node.js required for workspace checks; add the runtime to PATH"
    result = subprocess.run(
        [node, str(ROOT / "tests/acceptance/history_cases.mjs"), str(ROOT), case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok " + case


def test_history_module_and_accessible_controls(monkeypatch):
    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    engine = create_engine("postgresql+psycopg://")
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")

    def forbidden(*args, **kwargs):
        raise AssertionError("Static UI accessed database")

    try:
        monkeypatch.setattr(engine, "connect", forbidden)
        with TestClient(create_app(document_runtime=runtime)) as http:
            url = "/workspace/assets/history.js"
            response = http.get(url)
            assert response.status_code == 200
            assert response.content == (ROOT / "src/ara/workspace/static/history.js").read_bytes()
            assert response.headers["content-type"] == "application/javascript; charset=utf-8"
            assert response.headers["cache-control"] == "no-store"
            assert "script-src 'self'" in response.headers["content-security-policy"]
            assert response.headers["x-content-type-options"] == "nosniff"
            assert url not in http.get("/openapi.json").json()["paths"]
            from html.parser import HTMLParser

            class Page(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.tags = []

                def handle_starttag(self, tag, attrs):
                    self.tags.append((tag, dict(attrs)))

            page = Page()
            page.feed(http.get("/workspace").text)
            assert len([t for t, _ in page.tags if t == "script"]) == 1
            for name in ("edit-undo", "edit-redo"):
                (button,) = [a for t, a in page.tags if t == "button" and a.get("id") == name]
                assert button["type"] == "button"
                assert button.get("title")
        with TestClient(create_app()) as default:
            assert default.get("/workspace/assets/history.js").status_code == 404
    finally:
        engine.dispose()
