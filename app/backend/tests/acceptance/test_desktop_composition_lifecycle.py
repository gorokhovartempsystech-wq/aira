"""Accepted writes and startup Stop retain their Home until known completion."""

import importlib
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from test_desktop_composition import activate, api, closed, config, imported, ready, running
from test_desktop_server import http_for, wait_for
from test_docx_editor_http import command, control, opened, path, root
from test_licensing_policy import synthetic_key

from ara.desktop.data_home import HomeError, open_home
from ara.licensing.client import ActivationStore

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native fixture desktop lifecycle")


def test_accepted_real_editor_save_completes_before_pg_and_home_close(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    desktop = ready(api().FixtureDesktop(cfg))
    wiring = importlib.import_module("ara.desktop.composition._wiring")
    entered, release = Event(), Event()
    # Patch the real registry at application construction in a fresh launch.
    closed(desktop)
    create = wiring.create_app

    def application(**kwargs):
        app = create(**kwargs)
        original = app.state.docx_editor_registry.save

        def held(**values):
            entered.set()
            assert release.wait(8)
            return original(**values)

        monkeypatch.setattr(app.state.docx_editor_registry, "save", held)
        return app

    monkeypatch.setattr(wiring, "create_app", application)
    desktop = ready(api().FixtureDesktop(cfg))
    try:
        with http_for(desktop.connection()) as http, ThreadPoolExecutor(max_workers=1) as pool:
            activate(http)
            item, original = imported(http)
            view, _ = opened(http, item)
            response = http.post(
                path(item, view) + "/commands",
                json=command(view, "insert_text", "Finish accepted save "),
            )
            assert response.status_code == 200
            view = response.json()
            future = pool.submit(http.post, path(item, view) + "/save", json=control(view))
            try:
                assert entered.wait(3)
                assert not desktop.shutdown(0.02)
                assert desktop.view().resources_pending and desktop.connection() is None
                with pytest.raises(HomeError):
                    open_home(cfg.home)
            finally:
                release.set()
            saved = future.result(timeout=5)
            assert saved.status_code == 200 and not saved.json()["document"]["is_dirty"]
    finally:
        release.set()
        closed(desktop)
    monkeypatch.setattr(wiring, "create_app", create)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        wait_for(lambda: http.get("/desktop/license").json()["phase"] == "active")
        data = http.get(root(item) + "/content").content
        assert data != original
        view, _ = opened(http, item, mode="recover")
        assert (
            http.get(path(item, view) + "/view")
            .json()["projection"]["blocks"][0]["text"]
            .startswith("Finish accepted save ")
        )
        assert http.get(root(item)).json()["storage_revision"] == 2


def test_activation_store_write_holds_home_after_http_stops(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    entered, release = Event(), Event()
    original = ActivationStore.save

    def held(store, value):
        entered.set()
        assert release.wait(8)
        return original(store, value)

    monkeypatch.setattr(ActivationStore, "save", held)
    desktop = ready(api().FixtureDesktop(cfg))
    try:
        with http_for(desktop.connection()) as http:
            wait_for(lambda: http.get("/desktop/license").json()["phase"] == "activation_required")
            assert (
                http.post(
                    "/desktop/license/activate", json={"license_key": synthetic_key()}
                ).status_code
                == 202
            )
            assert entered.wait(3)
            assert not desktop.shutdown(0.05)
            assert desktop.view().resources_pending
            with pytest.raises(HomeError):
                open_home(cfg.home)
    finally:
        release.set()
        closed(desktop)
    assert ActivationStore(cfg.home / "license").load() is not None
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        wait_for(lambda: http.get("/desktop/license").json()["phase"] == "active")


def test_stop_during_home_acquisition_never_starts_pg_or_http(tmp_path, monkeypatch):
    wiring = importlib.import_module("ara.desktop.composition._wiring")
    cfg = config(tmp_path)
    entered, release = Event(), Event()
    original = wiring.open_home

    def held(*args):
        home = original(*args)
        entered.set()
        assert release.wait(5)
        return home

    monkeypatch.setattr(wiring, "open_home", held)
    desktop = api().FixtureDesktop(cfg)
    desktop.start()
    try:
        assert entered.wait(3)
        assert not desktop.shutdown(0.02)
        assert desktop.connection() is None
    finally:
        release.set()
        closed(desktop)
    assert desktop.view().phase == "closed"
    assert not list((cfg.home / "postgres").iterdir())
    assert not cfg.transport.requests


def test_application_setup_failure_retains_data_and_allows_known_retry(tmp_path, monkeypatch):
    wiring = importlib.import_module("ara.desktop.composition._wiring")
    cfg = config(tmp_path)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        item, before = imported(http)
    original = wiring.create_app

    def broken(**kwargs):
        raise ValueError("SYNTHETIC_PRIVATE")

    monkeypatch.setattr(wiring, "create_app", broken)
    desktop = api().FixtureDesktop(cfg)
    desktop.start()
    wait_for(
        lambda: desktop.view().phase == "failed" and not desktop.view().resources_pending,
        timeout=25,
    )
    assert desktop.view().error_code == "startup_failed"
    assert "SYNTHETIC_PRIVATE" not in repr(desktop.view())
    assert desktop.connection() is None and desktop.shutdown(0)
    monkeypatch.setattr(wiring, "create_app", original)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        wait_for(lambda: http.get("/desktop/license").json()["phase"] == "active")
        assert http.get(root(item) + "/content").content == before


def test_second_top_owner_is_rejected_until_first_has_drained(tmp_path):
    cfg = config(tmp_path)
    with running(cfg):
        other = api().FixtureDesktop(cfg)
        with pytest.raises(api().DesktopError) as caught:
            other.start()
        assert caught.value.code == "desktop_busy"
        assert other.shutdown(0)
