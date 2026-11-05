"""Native fixture backend start/save/check/restart on one disposable owned Home."""

import copy
import importlib
import os
import pickle
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_desktop_postgres_cluster import tools
from test_desktop_server import http_for, wait_for
from test_docx_analysis_http import poll, saved_request, started
from test_docx_editor_http import command, control, opened, path, root
from test_docx_review_v1 import fixture
from test_licensing_client_runtime import Clock, Transport
from test_licensing_client_transport import ORIGIN
from test_licensing_policy import DEVICE, synthetic_key

from ara.desktop.postgres_upgrade import UpgradeTools

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native owned fixture desktop")


def api():
    return importlib.import_module("ara.desktop.composition")


def config(tmp_path, **changes):
    pg = tools()
    return api().FixtureConfig(
        **(
            dict(
                home=tmp_path.resolve() / "SYNTHETIC_PRIVATE",
                postgres=pg,
                upgrade=UpgradeTools(
                    pg.postgres.parent / "pg_dump", pg.postgres.parent / "pg_restore"
                ),
                migrations=Path.cwd() / "migrations",
                license_origin=ORIGIN,
                device_provider=lambda: DEVICE,
                clock=Clock(),
                transport=Transport(),
            )
            | changes
        )
    )


def ready(desktop):
    desktop.start()
    wait_for(lambda: desktop.view().phase in ("ready", "failed"), timeout=25)
    assert desktop.view().phase == "ready", desktop.view()
    assert desktop.view().fixture and desktop.view().resources_pending
    assert desktop.connection() is not None
    return desktop


def closed(desktop):
    wait_for(lambda: desktop.shutdown(timeout=0.1), timeout=20)
    assert not desktop.view().resources_pending
    assert desktop.connection() is None


@contextmanager
def running(cfg):
    desktop = ready(api().FixtureDesktop(cfg))
    try:
        yield desktop
    finally:
        closed(desktop)


def license_phase(http, phase):
    return wait_for(
        lambda: v if (v := http.get("/desktop/license").json())["phase"] == phase else None
    )


def activate(http):
    license_phase(http, "activation_required")
    assert (
        http.post("/desktop/license/activate", json={"license_key": synthetic_key()}).status_code
        == 202
    )
    license_phase(http, "active")


def imported(http):
    item = SimpleNamespace(document_id=uuid4())
    data, _ = fixture()
    response = http.post(
        root(item) + "/import",
        params={"title": "Synthetic requirement"},
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code in (200, 201), response.text
    assert http.get(root(item) + "/content").content == data
    return item, data


def test_real_http_editor_fixture_analysis_restart_and_fresh_online_grant(tmp_path):
    cfg = config(tmp_path)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        assert http.get("/docx-documents").status_code == 403
        assert http.get("/health").status_code == 404
        activate(http)
        item, original = imported(http)
        view, _ = opened(http, item)
        response = http.post(
            path(item, view) + "/commands", json=command(view, "insert_text", "Saved ")
        )
        assert response.status_code == 200, response.text
        view = response.json()
        checkpoint = http.post(path(item, view) + "/checkpoint", json=control(view))
        assert checkpoint.status_code == 200, checkpoint.text
        view, body = saved_request(http, item, checkpoint.json())
        saved = http.get(root(item) + "/content").content
        assert saved != original
        location, _ = started(http, item, body)
        outcome = poll(http, location)
        assert outcome["fixture"] and outcome["state"]["status"] == "succeeded"
        result = http.get(root(item) + "/analysis-result").json()
        assert result["fixture"] and result["matches_saved_document"]
        metadata = http.get(root(item)).json()
        home_identity = (cfg.home / "identity.json").read_bytes()
    assert desktop.view().phase == "closed"
    with running(cfg) as reopened, http_for(reopened.connection()) as http:
        license_phase(http, "active")
        assert http.get(root(item)).json() == metadata
        assert http.get(root(item) + "/content").content == saved
        assert http.get(root(item) + "/analysis-result").json() == result
        assert (cfg.home / "identity.json").read_bytes() == home_identity
    requests = cfg.transport.requests
    assert [r.operation for r in requests] == ["activate", "check"]
    assert requests[0].nonce != requests[1].nonce


def test_constructor_empty_stop_pid_and_copy(tmp_path, monkeypatch):
    desktop = api().FixtureDesktop(config(tmp_path))
    assert desktop.view().phase == "new" and not desktop.view().resources_pending
    assert desktop.connection() is None and not desktop._config.home.exists()
    for call in (
        lambda: copy.copy(desktop),
        lambda: copy.deepcopy(desktop),
        lambda: pickle.dumps(desktop),
    ):
        with pytest.raises((TypeError, api().DesktopError)):
            call()
    with desktop._lock, monkeypatch.context() as patch:
        patch.setattr(os, "getpid", lambda: -1)
        for call in (desktop.view, desktop.start, desktop.connection, desktop.shutdown):
            with pytest.raises(api().DesktopError) as caught:
                call()
            assert caught.value.code == "invalid_handle"
    assert desktop.shutdown(0)
    assert desktop.view().phase == "closed" and not desktop._config.home.exists()


@pytest.mark.parametrize("value", [-1, 6, True, None, float("nan"), float("inf"), 10**1000])
def test_shutdown_rejects_invalid_budget(tmp_path, value):
    desktop = api().FixtureDesktop(config(tmp_path))
    with pytest.raises(api().DesktopError) as caught:
        desktop.shutdown(value)
    assert caught.value.code == "validation_error"
    assert desktop.view().phase == "new" and not desktop._config.home.exists()
