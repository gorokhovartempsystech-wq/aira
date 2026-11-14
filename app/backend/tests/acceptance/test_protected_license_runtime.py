"""Protected startup, migration and cleanup using explicit synthetic ports."""

import secrets
import threading

import pytest
from test_licensing_client_runtime import Clock, Transport, done
from test_licensing_client_transport import ORIGIN
from test_licensing_policy import DEVICE, synthetic_key

from ara.licensing.client import ActivationStore, ClientError, LicenseClient
from ara.model_protection.access_wire import AccessError


class Access:
    def __init__(self):
        self.key = secrets.token_bytes(32)
        self.enrolled = False
        self.fail = False
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()

    def unlock(self, permit, *, device_id, license_key=None, checkpoint):
        self.entered.set()
        assert self.release.wait(5)
        checkpoint()
        if self.fail:
            raise AccessError()
        if not self.enrolled and license_key is None:
            raise AccessError("enrollment_required")
        self.enrolled = True
        return self.key


def client(tmp_path, access, **kwargs):
    port, clock = kwargs.get("transport", Transport()), Clock()
    store = ActivationStore(tmp_path / "identity")
    result = LicenseClient(
        ORIGIN,
        store,
        clock=clock,
        transport=port,
        device_provider=lambda: DEVICE,
        model_access=access,
    )
    return result, store, port, clock


def denied(value):
    with pytest.raises(ClientError):
        value.require_model_key()


def test_existing_activation_requires_one_migration_and_then_automatic_start(tmp_path):
    access = Access()
    value, store, port, clock = client(tmp_path, access)
    # First prepare the old public-only identity through the original client.
    old = LicenseClient(ORIGIN, store, clock=clock, transport=port, device_provider=lambda: DEVICE)
    old.start(synthetic_key())
    assert done(old).phase == "active"
    assert old.shutdown()
    value.start()
    assert done(value).phase == "activation_required"
    denied(value)
    value.start(synthetic_key())
    assert done(value).phase == "active"
    assert value.require_model_key() == access.key
    assert value.shutdown()
    denied(value)
    again = LicenseClient(
        ORIGIN,
        store,
        clock=clock,
        transport=port,
        device_provider=lambda: DEVICE,
        model_access=access,
    )
    again.start()
    assert done(again).phase == "active"
    assert again.require_model_key() == access.key
    assert again.shutdown()


def test_model_access_failure_never_grants_product_access(tmp_path):
    access = Access()
    access.fail = True
    value, store, _, _ = client(tmp_path, access)
    value.start(synthetic_key())
    assert done(value).phase == "failed"
    denied(value)
    assert store.load() is None
    assert value.shutdown()


def test_expiry_and_close_clear_cached_model_access(tmp_path):
    access = Access()
    value, _, _, clock = client(tmp_path, access)
    value.start(synthetic_key())
    assert done(value).phase == "active"
    clock.value += 60_000_000_000
    denied(value)
    assert value.view().phase == "expired"
    assert value.shutdown()
    denied(value)


def test_close_during_proof_prevents_activation_store_write(tmp_path):
    access = Access()
    access.release.clear()
    value, store, _, _ = client(tmp_path, access)
    value.start(synthetic_key())
    assert access.entered.wait(5)
    value.close()
    access.release.set()
    assert value.shutdown()
    denied(value)
    assert store.load() is None
