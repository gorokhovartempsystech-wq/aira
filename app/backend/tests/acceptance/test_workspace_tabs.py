"""Frozen D03-08 tab identity, state lifetime, and safe asset/UI delivery."""

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
        "identity",
        "order",
        "state",
        "capacity",
        "close_right",
        "close_left",
        "close_inactive",
        "close_last",
        "missing",
        "invalid",
        "independent",
    ],
)
def test_tab_lifecycle(case):
    bundled = Path(sys.base_prefix).parent / "node/bin/node"
    node = shutil.which("node") or (str(bundled) if bundled.is_file() else None)
    assert node is not None, "Node.js required for workspace checks; add the runtime to PATH"
    result = subprocess.run(
        [node, str(ROOT / "tests/acceptance/tabs_cases.mjs"), str(ROOT), case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok " + case


def test_tabs_asset_and_accessible_shell(monkeypatch):
    from html.parser import HTMLParser

    class Page(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []

        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))

    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    engine = create_engine("postgresql+psycopg://")
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")

    def forbidden(*args, **kwargs):
        raise AssertionError("Static workspace accessed database")

    try:
        monkeypatch.setattr(engine, "connect", forbidden)
        with TestClient(create_app(document_runtime=runtime)) as http:
            url = "/workspace/assets/tabs.js"
            response = http.get(url)
            assert response.status_code == 200
            assert response.content == (ROOT / "src/ara/workspace/static/tabs.js").read_bytes()
            assert response.headers["content-type"] == "application/javascript; charset=utf-8"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "script-src 'self'" in response.headers["content-security-policy"]
            assert url not in http.get("/openapi.json").json()["paths"]
            page = Page()
            page.feed(http.get("/workspace").text)
            assert len([t for t, _ in page.tags if t == "script"]) == 1
            assert any(a.get("role") == "tablist" for _, a in page.tags)
            assert any(a.get("role") == "tabpanel" for _, a in page.tags)
            assert any(t == "dialog" and a.get("id") == "close-tab-dialog" for t, a in page.tags)
            assert any(t == "button" and a.get("id") == "reload-document" for t, a in page.tags)
        with TestClient(create_app()) as default:
            assert default.get("/workspace/assets/tabs.js").status_code == 404
    finally:
        engine.dispose()
