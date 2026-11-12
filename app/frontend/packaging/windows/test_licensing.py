"""Portable admission/lifecycle checks; native EXE acceptance is separate."""

import asyncio
import importlib.machinery
import importlib.util
import json
import secrets
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "backend" / "src"))
sys.path.insert(0, str(HERE))

from aira_licensed_app import NativeApplication, trusted_page  # noqa: E402

from ara import licensing as core  # noqa: E402
from ara.licensing.client import ActivationStore, ClientError, LicenseClient  # noqa: E402

LOCAL = "http://127.0.0.1:8767"
DEVICE = "dv1-" + "a" * 64
BASE = 1_800_000_000_000
DOCUMENT = "/docx-documents/10000000-0000-0000-0000-000000000001"
SESSION = DOCUMENT + "/editor-sessions/20000000-0000-0000-0000-000000000001"
KEY = "AIRA-11112222-33334444-55556666-77778888"  # synthetic fixture


class Clock:
    value = 1_000_000_000

    def now_ns(self):
        return self.value


class Transport:
    def __init__(self):
        self.license_id = uuid4()
        self.requests = []
        self.error = None

    def execute(self, request, checkpoint):
        self.requests.append(request)
        if self.error:
            raise self.error
        return core.encode_grant(
            core.LaunchGrant(
                request.operation,
                self.license_id,
                request.device_id,
                request.nonce,
                BASE,
                BASE,
                BASE + 60_000,
            )
        )


class Inner:
    def __init__(self):
        self.scopes = []

    async def __call__(self, scope, receive, send):
        self.scopes.append(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"fixture":true}'})


def settled(client):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        state = client.view()
        if state.phase != "checking" and state.retry_available:
            return state
        time.sleep(0.005)
    raise AssertionError("Synthetic verification did not settle")


def new_client(store, clock, transport):
    return LicenseClient(
        "https://license.example.test",
        store,
        clock=clock,
        transport=transport,
        device_provider=lambda: DEVICE,
    )


@pytest.fixture
def world(tmp_path):
    clock, transport, inner = Clock(), Transport(), Inner()
    store, token = ActivationStore(tmp_path / "license"), secrets.token_bytes(32)
    client = new_client(store, clock, transport)
    host = NativeApplication(inner, client, origin=LOCAL, token=token)
    result = SimpleNamespace(
        clock=clock,
        transport=transport,
        inner=inner,
        store=store,
        token=token,
        client=client,
        app=host,
    )
    yield result
    assert client.shutdown(timeout=5)


def request(world, path, method="GET", body=None, token=True, origin=LOCAL):
    raw = json.dumps(body).encode() if body is not None else b""
    headers = [(b"host", b"127.0.0.1:8767"), (b"origin", origin.encode())]
    if token:
        headers.append((b"x-aira-session", world.token.hex().encode()))
    if method == "POST":
        headers.extend(
            [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
        )
    scope = dict(
        type="http",
        asgi={"version": "3.0"},
        http_version="1.1",
        method=method,
        scheme="http",
        path=path,
        raw_path=path.encode(),
        query_string=b"",
        root_path="",
        server=("127.0.0.1", 8767),
        client=("127.0.0.1", 50001),
        headers=headers,
    )
    sent = []

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(value):
        sent.append(value)

    asyncio.run(world.app(scope, receive, send))
    status = next(x["status"] for x in sent if x["type"] == "http.response.start")
    data = b"".join(x.get("body", b"") for x in sent if x["type"] == "http.response.body")
    return status, json.loads(data)


def activate(world):
    world.client.start()
    assert settled(world.client).phase == "activation_required"
    assert request(world, "/desktop/license/activate", "POST", {"license_key": KEY})[0] == 202
    assert settled(world.client).phase == "active"


def test_ui_visible_but_docs_and_http_bootstrap_closed_before_activation(world):
    world.client.start()
    assert request(world, "/aira/", token=False)[0] == 200
    assert request(world, "/aira/assets/js/main.mjs", token=False)[0] == 200
    assert request(world, "/docx-documents")[0] == 403
    assert request(world, "/aira/connection", token=False)[0] == 403
    assert request(world, "/aira/connection")[0] == 404
    status, body = request(world, "/desktop/license")
    assert status == 200 and body["phase"] == "activation_required"


def test_real_access_gate_opens_only_after_activation(world):
    activate(world)
    assert request(world, "/docx-documents")[0] == 200
    assert request(world, SESSION + "/commands", "POST", {})[0] == 200
    assert all(name != b"x-aira-session" for name, _ in world.inner.scopes[-1]["headers"])
    assert request(world, "/desktop/license", token=False)[0] == 403
    assert request(world, "/desktop/license", origin="https://foreign.example")[0] == 403


@pytest.mark.parametrize("error", ["network_unavailable", "license_disabled"])
def test_new_process_state_requires_online_check_and_does_not_reuse_access(world, error):
    activate(world)
    assert request(world, "/docx-documents")[0] == 200
    assert world.client.shutdown(timeout=5)
    world.transport.error = ClientError(error)
    client = new_client(world.store, world.clock, world.transport)
    try:
        world.app = NativeApplication(world.inner, client, origin=LOCAL, token=world.token)
        assert request(world, "/docx-documents")[0] == 403
        client.start()
        assert settled(client).error_code == error
        assert world.transport.requests[-1].operation == "check"
        assert world.transport.requests[-1].license_key is None
        assert request(world, "/docx-documents")[0] == 403
    finally:
        assert client.shutdown(timeout=5)


def test_expiry_keeps_preservation_but_blocks_new_changes(world):
    activate(world)
    assert request(world, "/docx-documents")[0] == 200
    world.clock.value += 60_000_000_001
    assert request(world, SESSION + "/commands", "POST", {})[0] == 403
    assert request(world, SESSION + "/saved-content", "POST", {})[0] == 200
    status, body = request(world, "/desktop/license")
    assert status == 200 and body["preservation_available"] is True


def test_reopen_checks_saved_activation_without_key_or_new_period(world):
    activate(world)
    first = settled(world.client)
    assert world.client.shutdown(timeout=5)
    client = new_client(world.store, world.clock, world.transport)
    try:
        world.app = NativeApplication(world.inner, client, origin=LOCAL, token=world.token)
        client.start()
        again = settled(client)
        assert again.phase == "active"
        assert again.license_id == first.license_id
        assert again.expires_at_ms == first.expires_at_ms
        assert world.transport.requests[-1].operation == "check"
        assert world.transport.requests[-1].license_key is None
        assert request(world, "/docx-documents")[0] == 200
    finally:
        assert client.shutdown(timeout=5)


@pytest.mark.parametrize(
    "current",
    [
        None,
        "https://foreign.example/aira/",
        LOCAL + "/other",
        LOCAL + "/aira/?token=x",
        "file:///tmp/index.html",
        "http://127.0.0.1:8768/aira/",
        "http://user@127.0.0.1:8767/aira/",
    ],
)
def test_native_bridge_rejects_foreign_pages(current):
    assert not trusted_page(current, LOCAL + "/aira/")
    assert trusted_page(LOCAL + "/aira/#desktop", LOCAL + "/aira/")


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    loader = importlib.machinery.SourceFileLoader(
        "aira_windows_test_launcher", str(HERE / "aira_launcher.pyw")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, "DATA", tmp_path)
    monkeypatch.setattr(module, "STATE", tmp_path / "state.json")
    return module


def test_server_wires_native_capability_and_drains_license(world, launcher, monkeypatch):
    import aira_licensed_app

    token_seen = []
    world.inner.state = SimpleNamespace(
        aira_connection={"origin": LOCAL, "sessionToken": world.token.hex()}
    )

    def build_app(**kwargs):
        token_seen.append(kwargs["native_token"])
        return world.inner

    class FakeServer:
        def __init__(self, config):
            self.started = self.should_exit = False

        def run(self):
            self.started = True
            while not self.should_exit:
                time.sleep(0.005)

    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "executable", sys.executable)
    monkeypatch.setitem(sys.modules, "aira_host", SimpleNamespace(build_app=build_app))
    monkeypatch.setitem(
        sys.modules, "uvicorn", SimpleNamespace(Config=lambda app, **kw: app, Server=FakeServer)
    )
    monkeypatch.setattr(aira_licensed_app, "create_license_client", lambda *args: world.client)
    import ara.desktop.access

    monkeypatch.setattr(ara.desktop.access, "new_session_token", lambda: world.token)
    monkeypatch.setattr(launcher, "pick_port", lambda preferred: 8767)
    server = launcher.Server()
    try:
        assert server.start(5432, lambda message: None) == LOCAL + "/aira/"
        assert token_seen == [world.token.hex()]
        assert settled(world.client).phase == "activation_required"
        assert server.connection["origin"] == LOCAL
    finally:
        server.stop()
    assert world.client.view().phase == "closed"
    assert server.connection is None


def test_unconfirmed_server_stop_keeps_license_and_database_owned(launcher, monkeypatch):
    calls = []
    server = launcher.Server()
    server.server = SimpleNamespace(should_exit=False)
    server.thread = SimpleNamespace(is_alive=lambda: True, join=lambda timeout: None)
    server.license_client = SimpleNamespace(shutdown=lambda timeout: calls.append("license"))
    launcher.STATE.write_text("synthetic-state")
    monkeypatch.setattr(launcher, "stop_postgres", lambda: calls.append("postgres"))
    with pytest.raises(launcher.LaunchError):
        launcher.shutdown_backend(server)
    assert calls == [] and launcher.STATE.read_text() == "synthetic-state"


def test_license_drain_failure_does_not_report_clean_shutdown(launcher, monkeypatch):
    server = launcher.Server()
    server.license_client = SimpleNamespace(shutdown=lambda timeout: False)
    calls = []
    monkeypatch.setattr(launcher, "stop_postgres", lambda: calls.append("postgres"))
    with pytest.raises(launcher.LaunchError):
        launcher.shutdown_backend(server)
    assert calls == []


def test_browser_flag_cannot_open_unlicensed_fallback(launcher, monkeypatch):
    calls = []
    kernel = SimpleNamespace(CreateMutexW=lambda *args: 1, GetLastError=lambda: 0)
    user = SimpleNamespace(MessageBoxW=lambda *args: calls.append("error"))
    monkeypatch.setattr(
        launcher.ctypes, "windll", SimpleNamespace(kernel32=kernel, user32=user), raising=False
    )
    monkeypatch.setenv("AIRA_BROWSER_MODE", "1")
    monkeypatch.setattr(launcher, "open_log", lambda: Path("synthetic.log"))
    monkeypatch.setitem(
        sys.modules, "aira_updates", SimpleNamespace(startup_update=lambda *args: False)
    )
    monkeypatch.setattr(launcher, "run_browser", lambda *args: calls.append("browser"))
    monkeypatch.setattr(launcher, "run_desktop", lambda *args: calls.append("desktop"))
    with pytest.raises(SystemExit) as error:
        launcher.main()
    assert error.value.code == 1 and calls == ["error"]


def test_bridge_does_not_disclose_capability_to_another_page(launcher):
    server = SimpleNamespace(url=LOCAL + "/aira/", connection={"sessionToken": "synthetic"})
    window = SimpleNamespace(get_current_url=lambda: "https://foreign.example/")
    bridge = launcher.DesktopApi({"server": server, "window": window})
    with pytest.raises(launcher.LaunchError):
        bridge.connection()
    window.get_current_url = lambda: LOCAL + "/aira/#desktop"
    assert bridge.connection() == server.connection
    assert bridge.connection() is not server.connection
