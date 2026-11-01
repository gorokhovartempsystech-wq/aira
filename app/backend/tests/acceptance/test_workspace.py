"""Independent D03-01 delivery and isolation checks; UI is verified in a browser."""

import importlib
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
ASSETS = (
    ("/workspace", "text/html", "index.html"),
    ("/workspace/assets/app.css", "text/css", "app.css"),
    ("/workspace/assets/app.js", "application/javascript", "app.js"),
)


@pytest.fixture
def http(monkeypatch):
    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    engine = create_engine("postgresql+psycopg://")

    def forbidden(*args, **kwargs):
        raise AssertionError("UI shell must not access database or dispose caller engine")

    with monkeypatch.context() as patch:
        patch.setattr(engine, "connect", forbidden)
        patch.setattr(engine, "dispose", forbidden)
        runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
        with TestClient(create_app(document_runtime=runtime)) as http:
            yield http
    engine.dispose()


@pytest.mark.parametrize("url,mime,filename", ASSETS)
def test_fixed_assets_no_db_and_safe_headers(http, url, mime, filename):
    response = http.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == mime + "; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.content == (ROOT / "src/ara/workspace/static" / filename).read_bytes()
    csp = response.headers["content-security-policy"]
    for rule in (
        "connect-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    ):
        assert rule in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"


def test_html_references_only_same_origin_assets_and_accessible_form(http):
    from html.parser import HTMLParser

    class Page(HTMLParser):
        def __init__(self):
            super().__init__()
            self.nodes = []

        def handle_starttag(self, tag, attrs):
            self.nodes.append((tag, dict(attrs)))

    response = http.get("/workspace")
    assert response.status_code == 200
    page = Page()
    page.feed(response.text)
    scripts = [a for tag, a in page.nodes if tag == "script"]
    assert len(scripts) == 1
    assert scripts[0]["src"] == "/workspace/assets/app.js"
    assert any(
        tag == "link" and a.get("href") == "/workspace/assets/app.css" for tag, a in page.nodes
    )
    assert any(tag == "html" and a.get("lang") == "ru" for tag, a in page.nodes)
    assert any(a.get("aria-live") in ("polite", "assertive") for _, a in page.nodes)
    assert any(
        tag == "input" and a.get("type") == "file" and a.get("accept") == ".docx"
        for tag, a in page.nodes
    )
    assert not any("style" in a or any(k.startswith("on") for k in a) for _, a in page.nodes)
    assert not any(tag == "iframe" for tag, _ in page.nodes)
    assert "AIRA" in response.text


@pytest.mark.parametrize(
    "url",
    [
        "/workspace/assets/missing.js",
        "/workspace/assets/secrets.env",
        "/workspace/assets/%2e%2e/%2e%2e/pyproject.toml",
        "/workspace/assets/index.html",
        "/workspace/assets/app.py",
    ],
)
def test_no_arbitrary_file_access(http, url):
    response = http.get(url)
    assert response.status_code == 404
    assert "[project]" not in response.text


@pytest.mark.parametrize("url,mime,filename", ASSETS)
def test_default_factory_has_no_workspace(url, mime, filename):
    with TestClient(create_app()) as http:
        assert http.get(url).status_code == 404


def test_ui_is_not_an_extra_product_openapi_endpoint(http):
    assert http.get("/workspace").status_code == 200
    schema = http.get("/openapi.json").json()
    assert not any(p.startswith("/workspace") for p in schema["paths"])
    assert {"get", "put"} == set(schema["paths"]["/docx-documents/{document_id}/content"])


def test_workspace_import_and_install_are_inert():
    code = """
import importlib, builtins, io
from pathlib import Path
from fastapi import FastAPI
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected asset I/O during import or setup')
for target, name in ((builtins,'open'), (io,'open'), (Path,'open'),
                     (Path,'read_text'), (Path,'read_bytes')):
    setattr(target, name, forbidden)
module = importlib.import_module('ara.workspace')
module.install_workspace(FastAPI())
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_package_data_is_explicit():
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert set(config["tool"]["setuptools"]["package-data"]["ara.workspace"]) == {
        "static/*.html",
        "static/*.css",
        "static/*.js",
    }
    assert importlib.util.find_spec("ara.workspace") is not None
