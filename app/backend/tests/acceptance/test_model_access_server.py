"""Real PostgreSQL, synthetic licenses/keys and in-memory client vaults only."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from test_licensing_policy import DEVICE, OTHER, synthetic_key
from test_licensing_server import license_world  # noqa: F401

from ara import licensing as core
from ara.licensing.server import ServerError
from ara.model_protection.access_wire import DOMAIN, VERSION, AccessError, canonical
from ara.model_protection.client import ModelAccessClient
from ara.model_protection.server import (
    ModelAccessService,
    Release,
    attach_model_access,
    initialize_model_access,
)


@pytest.fixture
def model_world(request):
    w = request.getfixturevalue("license_world")
    initialize_model_access(w["engine"])
    release = Release("models-0.2m-r1", secrets.token_hex(32), secrets.token_bytes(32))
    service = ModelAccessService(w["runtime"], (release,))
    app = w["a"].create_license_app(w["runtime"])
    attach_model_access(app, service)
    return dict(w=w, service=service, release=release, app=app)


def challenge(m, private, *, operation="enroll", **changes):
    w, r = m["w"], m["release"]
    body = (
        dict(
            schema_version=VERSION,
            operation=operation,
            license_id=str(w["id"]),
            license_key=w["key"] if operation == "enroll" else None,
            device_id=DEVICE,
            public_key=private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex(),
            client_nonce=secrets.token_hex(32),
            release_id=r.release_id,
            manifest_sha256=r.manifest_sha256,
        )
        | changes
    )
    return body, m["service"].challenge(body)["token"]


def proof(token, private):
    return dict(
        schema_version=VERSION, token=token, signature=private.sign(DOMAIN + token.encode()).hex()
    )


def enroll(m, private):
    body, token = challenge(m, private)
    return body, m["service"].complete(proof(token, private))


def test_enroll_unlock_and_old_api_coexist_without_extending_period(model_world):
    m = model_world
    private = Ed25519PrivateKey.generate()
    _, first = enroll(m, private)
    assert first["key"] == m["release"].key.hex()
    w = m["w"]
    w["clock"][0] += 1000
    _, token = challenge(m, private, operation="unlock")
    second = m["service"].complete(proof(token, private))
    assert second["expires_at_ms"] == first["expires_at_ms"]
    old = w["a"].process_request(
        w["runtime"], core.StartRequest("check", DEVICE, secrets.token_hex(32), license_id=w["id"])
    )
    assert core.decode_grant(old).expires_at_ms == first["expires_at_ms"]
    initialize_model_access(w["engine"])


def test_invalid_proof_does_not_consume_valid_challenge(model_world):
    m = model_world
    private = Ed25519PrivateKey.generate()
    _, token = challenge(m, private)
    with pytest.raises(AccessError):
        m["service"].complete(proof(token, Ed25519PrivateKey.generate()))
    assert m["service"].complete(proof(token, private))["key"] == m["release"].key.hex()
    with pytest.raises((AccessError, ServerError)):
        m["service"].complete(proof(token, private))


@pytest.mark.parametrize("change", ["revoked", "expired", "challenge_expired", "clock_backwards"])
def test_state_is_rechecked_at_completion(model_world, change):
    m, private = model_world, Ed25519PrivateKey.generate()
    _, token = challenge(m, private)
    w = m["w"]
    if change == "revoked":
        w["a"].set_enabled(w["runtime"], license_id=w["id"], enabled=False)
    elif change in {"expired", "challenge_expired"}:
        w["clock"][0] += 60_000
    else:
        w["clock"][0] -= 1
    with pytest.raises((AccessError, ServerError, core.LicenseError)):
        m["service"].complete(proof(token, private))


def test_only_one_concurrent_completion_can_get_key(model_world):
    m, private = model_world, Ed25519PrivateKey.generate()
    _, token = challenge(m, private)
    body = proof(token, private)

    def finish(_):
        try:
            return m["service"].complete(body)["key"] == m["release"].key.hex()
        except (AccessError, ServerError):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(finish, range(2))).count(True) == 1


def test_rotation_invalidates_pending_proofs_and_old_device_key(model_world):
    m = model_world
    old, new = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    enroll(m, old)
    _, pending = challenge(m, old, operation="unlock")
    _, stale_enrollment = challenge(m, old)
    enroll(m, new)
    for token in (pending, stale_enrollment):
        with pytest.raises((AccessError, ServerError)):
            m["service"].complete(proof(token, old))
    with pytest.raises((AccessError, ServerError)):
        challenge(m, old, operation="unlock")
    _, token = challenge(m, new, operation="unlock")
    assert m["service"].complete(proof(token, new))["key"] == m["release"].key.hex()


@pytest.mark.parametrize(
    "changes",
    [
        {"license_key": synthetic_key()},
        {"release_id": "unknown"},
        {"manifest_sha256": "0" * 64},
        {"device_id": OTHER},
    ],
)
def test_wrong_identity_license_or_release_gets_no_key(model_world, changes):
    m, private = model_world, Ed25519PrivateKey.generate()
    enroll(m, private)
    with pytest.raises((AccessError, ServerError, core.LicenseError)):
        challenge(m, private, **changes)


def test_token_mac_and_signature_binding(model_world):
    m, private = model_world, Ed25519PrivateKey.generate()
    _, token = challenge(m, private)
    changed = token[:-1] + ("0" if token[-1] != "0" else "1")
    with pytest.raises(AccessError):
        m["service"].complete(proof(changed, private))
    assert m["service"].complete(proof(token, private))["key"] == m["release"].key.hex()


class MemoryVault:
    def __init__(self):
        self.keys = {}

    def load(self, license_id, device_id):
        return self.keys.get((license_id, device_id))

    def save(self, license_id, device_id, value):
        self.keys[license_id, device_id] = value


class LocalTransport:
    def __init__(self, app):
        self.app = app

    def execute(self, operation, body, checkpoint):
        checkpoint()
        with TestClient(self.app, base_url="https://license.example") as http:
            reply = http.post(
                "/license/model/v1/" + operation,
                content=canonical(body),
                headers={"Content-Type": "application/json"},
            )
        assert reply.headers["cache-control"] == "no-store"
        if reply.status_code != 200:
            raise AccessError()
        return reply.json()


def test_client_requires_migration_once_then_unlocks_without_key(model_world):
    m, vault = model_world, MemoryVault()
    w, r = m["w"], m["release"]
    grant = core.decode_grant(
        w["a"].process_request(
            w["runtime"],
            core.StartRequest("activate", DEVICE, secrets.token_hex(32), license_key=w["key"]),
        )
    )
    permit = SimpleNamespace(license_id=w["id"], expires_at_ms=grant.expires_at_ms)
    client = ModelAccessClient(
        "https://license.example",
        r.release_id,
        r.manifest_sha256,
        vault=vault,
        transport=LocalTransport(m["app"]),
    )
    with pytest.raises(AccessError) as caught:
        client.unlock(permit, device_id=DEVICE, checkpoint=lambda: None)
    assert caught.value.code == "enrollment_required"
    assert (
        client.unlock(permit, device_id=DEVICE, license_key=w["key"], checkpoint=lambda: None)
        == r.key
    )
    assert client.unlock(permit, device_id=DEVICE, checkpoint=lambda: None) == r.key
    assert len(vault.keys) == 1


def test_http_requires_https_and_has_no_secret_errors(model_world):
    m, private = model_world, Ed25519PrivateKey.generate()
    body, _ = challenge(m, private)
    with TestClient(m["app"], base_url="http://license.example") as http:
        response = http.post("/license/model/v1/challenge", json=body)
        assert response.status_code == 403
        assert m["w"]["key"] not in response.text
        assert m["release"].key.hex() not in response.text
        assert response.headers["cache-control"] == "no-store"
