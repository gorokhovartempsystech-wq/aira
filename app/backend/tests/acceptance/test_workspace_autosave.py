"""D03-06 frozen scheduler behavior and same-origin module delivery."""

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
URL = "/workspace/assets/autosave.js"


@pytest.mark.parametrize(
    "case",
    [
        "deadline",
        "unchanged",
        "continuous",
        "blocked",
        "overlap",
        "stop",
        "stale",
        "errors",
        "paused",
        "second_cycle",
    ],
)
def test_scheduler_behavior(case):
    bundled = Path(sys.base_prefix).parent / "node/bin/node"
    node = shutil.which("node") or (str(bundled) if bundled.is_file() else None)
    assert node is not None, "Node.js required for workspace checks; add the runtime to PATH"
    result = subprocess.run(
        [node, str(ROOT / "tests/acceptance/autosave_cases.mjs"), str(ROOT), case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok " + case


def test_autosave_module_is_fixed_safe_and_inert(monkeypatch):
    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    engine = create_engine("postgresql+psycopg://")
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")

    def forbidden(*args, **kwargs):
        raise AssertionError("Asset loading reached DB")

    try:
        monkeypatch.setattr(engine, "connect", forbidden)
        with TestClient(create_app(document_runtime=runtime)) as http:
            response = http.get(URL)
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/javascript; charset=utf-8"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "script-src 'self'" in response.headers["content-security-policy"]
            assert response.content == (ROOT / "src/ara/workspace/static/autosave.js").read_bytes()
            assert URL not in http.get("/openapi.json").json()["paths"]
            assert 'type="module"' in http.get("/workspace").text
            assert http.get("/workspace/assets/autosave_cases.mjs").status_code == 404
        with TestClient(create_app()) as default:
            assert default.get(URL).status_code == 404
    finally:
        engine.dispose()
