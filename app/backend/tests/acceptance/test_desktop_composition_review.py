"""Crash recovery, continuous startup budget and live component failure."""

import importlib
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import UUID

import pytest
from test_desktop_composition import activate, api, closed, config, imported, ready, running
from test_desktop_postgres_cluster_recovery import wait_for_slot
from test_desktop_server import http_for, wait_for
from test_docx_editor_http import command, control, opened, path, root

from ara.licensing.client import ActivationStore

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native fixture desktop review")


def test_accepted_save_restart_exports_exact_editor_bytes(tmp_path, monkeypatch):
    wiring = importlib.import_module("ara.desktop.composition._wiring")
    create = wiring.create_app
    apps = []

    def capture(**kwargs):
        app = create(**kwargs)
        apps.append(app)
        return app

    monkeypatch.setattr(wiring, "create_app", capture)
    cfg = config(tmp_path)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        item, original = imported(http)
        view, _ = opened(http, item)
        edited = http.post(
            path(item, view) + "/commands", json=command(view, "insert_text", "Exact saved bytes ")
        )
        assert edited.status_code == 200
        view = edited.json()
        expected = (
            apps[0]
            .state.docx_editor_registry.snapshot(
                document_id=item.document_id, session_id=UUID(view["session_id"])
            )
            .editor.document.data
        )
        assert expected != original
        assert http.post(path(item, view) + "/save", json=control(view)).status_code == 200
        assert http.get(root(item) + "/content").content == expected
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        wait_for(lambda: http.get("/desktop/license").json()["phase"] == "active")
        assert http.get(root(item) + "/content").content == expected


@pytest.mark.parametrize("clock_fault", ["deadline", "backwards", "invalid"])
def test_startup_clock_fault_never_publishes_ready_or_starts_pg(tmp_path, monkeypatch, clock_fault):
    wiring = importlib.import_module("ara.desktop.composition._wiring")
    now = [1_000_000_000]
    monkeypatch.setattr(wiring, "DarwinClock", lambda: SimpleNamespace(now_ns=lambda: now[0]))
    entered, release = Event(), Event()
    original = wiring.open_home

    def held(*args):
        home = original(*args)
        entered.set()
        assert release.wait(5)
        return home

    monkeypatch.setattr(wiring, "open_home", held)
    cfg = config(tmp_path)
    desktop = api().FixtureDesktop(cfg)
    desktop.start()
    try:
        assert entered.wait(3)
        now[0] = (
            now[0] + wiring.STARTUP_NS + 1
            if clock_fault == "deadline"
            else 0
            if clock_fault == "backwards"
            else True
        )
    finally:
        release.set()
    wait_for(lambda: desktop.view().phase == "failed" and not desktop.view().resources_pending)
    expected = "startup_timeout" if clock_fault == "deadline" else "clock_unavailable"
    assert desktop.view().error_code == expected and desktop.connection() is None
    assert desktop.shutdown(0)
    assert list((cfg.home / "postgres").iterdir()) == []


def test_live_component_failure_fences_http_and_preserves_document(tmp_path, monkeypatch):
    wiring = importlib.import_module("ara.desktop.composition._wiring")
    original = wiring.Session.healthy
    cfg = config(tmp_path)
    desktop = ready(api().FixtureDesktop(cfg))
    try:
        with http_for(desktop.connection()) as http:
            activate(http)
            item, before = imported(http)
        monkeypatch.setattr(wiring.Session, "healthy", lambda self: False)
        wait_for(lambda: desktop.view().error_code == "runtime_failed")
        assert desktop.connection() is None
    finally:
        closed(desktop)
    monkeypatch.setattr(wiring.Session, "healthy", original)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        wait_for(lambda: http.get("/desktop/license").json()["phase"] == "active")
        assert http.get(root(item) + "/content").content == before


def test_parent_exit_after_acknowledged_http_import_reopens_exact_docx(tmp_path):
    script = r"""
import json,os,sys
from pathlib import Path
from hashlib import sha256
from test_desktop_composition import api,config,ready,activate,imported
from test_desktop_server import http_for
cfg=config(Path(sys.argv[1]))
d=ready(api().FixtureDesktop(cfg))
with http_for(d.connection()) as http:
    activate(http)
    item,data=imported(http)
(Path(sys.argv[1])/'proof.json').write_text(json.dumps(dict(id=str(item.document_id),sha256=sha256(data).hexdigest())))
os._exit(73)
"""
    response = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path.resolve())],
        env={"PYTHONPATH": str(Path.cwd() / "src") + ":" + str(Path.cwd() / "tests/acceptance")},
        capture_output=True,
        timeout=35,
    )
    assert response.returncode == 73, response.stderr.decode()
    cfg = config(tmp_path)
    wait_for_slot(cfg.home / "postgres")
    cfg.transport.id = ActivationStore(cfg.home / "license").load().license_id
    proof = json.loads((tmp_path / "proof.json").read_text())
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        wait_for(lambda: http.get("/desktop/license").json()["phase"] == "active")
        result = http.get("/docx-documents/" + proof["id"] + "/content")
        assert result.status_code == 200 and sha256(result.content).hexdigest() == proof["sha256"]
