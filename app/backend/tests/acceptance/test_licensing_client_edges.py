"""Additional review acceptance: clocks, native Windows ABI and stale results."""

import ctypes
import importlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from test_licensing_client_identity import Function
from test_licensing_client_runtime import Clock, Transport, done
from test_licensing_client_store import api, reject
from test_licensing_client_transport import ORIGIN
from test_licensing_policy import DEVICE, synthetic_key


def test_windows_replace_abi_and_failure_are_fixed(monkeypatch, tmp_path):
    module = importlib.import_module("ara.licensing.client._store")
    calls = []
    result = [1]

    def move(source, target, flags):
        calls.append((source, target, flags))
        return result[0]

    function = Function(move)
    library = type("Library", (), {"MoveFileExW": function})()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: library, raising=False)
    source, target = tmp_path / "source", tmp_path / "target"
    module._windows_replace(source, target)
    assert calls == [(str(source), str(target), 9)]
    assert function.argtypes == [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    assert function.restype is ctypes.c_int32
    result[0] = 0
    reject("activation_store_error", lambda: module._windows_replace(source, target))


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows native activation storage release gate"
)
def test_windows_native_store_replace(tmp_path):
    store = api().ActivationStore(tmp_path / "identity")
    for _ in range(3):
        value = api().ActivationIdentity(uuid4(), DEVICE)
        store.save(value)
        assert api().ActivationStore(tmp_path / "identity").load() == value


def test_save_delay_cannot_publish_after_verification_deadline(tmp_path, monkeypatch):
    clock, transport = Clock(), Transport()
    store = api().ActivationStore(tmp_path)
    original = store.save

    def delayed(value):
        original(value)
        clock.value += 15_000_000_001

    monkeypatch.setattr(store, "save", delayed)
    client = api().LicenseClient(
        ORIGIN, store, clock=clock, transport=transport, device_provider=lambda: DEVICE
    )
    try:
        client.start(synthetic_key())
        assert done(client).error_code == "verification_timeout"
        assert store.load() is not None
        reject("access_denied", client.require_active)
    finally:
        client.close()


def test_corrupt_identity_requires_explicit_reactivation(tmp_path):
    file = tmp_path / "license-activation.json"
    file.write_bytes(b"corrupt")
    store, transport = api().ActivationStore(tmp_path), Transport()
    client = api().LicenseClient(
        ORIGIN, store, clock=Clock(), transport=transport, device_provider=lambda: DEVICE
    )
    try:
        client.start()
        assert done(client).error_code == "activation_store_error"
        assert not transport.requests and file.read_bytes() == b"corrupt"
        client.start(synthetic_key())
        assert done(client).phase == "active"
        assert json.loads(file.read_bytes())["license_id"] == str(transport.id)
    finally:
        client.close()


def test_check_reply_for_another_license_id_rejected(tmp_path):
    store, transport = api().ActivationStore(tmp_path), Transport()
    store.save(api().ActivationIdentity(uuid4(), DEVICE))
    client = api().LicenseClient(
        ORIGIN, store, clock=Clock(), transport=transport, device_provider=lambda: DEVICE
    )
    before = (tmp_path / "license-activation.json").read_bytes()
    try:
        client.start()
        assert done(client).error_code == "invalid_response"
        assert (tmp_path / "license-activation.json").read_bytes() == before
    finally:
        client.close()


def test_factories_do_not_touch_native_libraries_files_or_network(tmp_path, monkeypatch):
    import httpx

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected I/O from constructor")

    a = api()
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", forbidden)
        patch.setattr(os, "open", forbidden)
        patch.setattr(ctypes, "CDLL", forbidden)
        patch.setattr(ctypes, "WinDLL", forbidden, raising=False)
        patch.setattr(httpx, "Client", forbidden)
        store = a.ActivationStore(tmp_path / "absent")
        a.HttpsTransport(ORIGIN)
        client = a.LicenseClient(ORIGIN, store)
        assert client.view().phase == "new"
        client.close()
    assert not (tmp_path / "absent").exists()
