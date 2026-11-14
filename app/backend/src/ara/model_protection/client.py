"""Explicit proof-of-possession client and native credential vault."""

import hashlib
import secrets
import sys
import time

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from ara.licensing.client._transport import checked_origin

from .access_wire import (
    DOMAIN,
    VERSION,
    AccessError,
    canonical,
    decode,
    hex_text,
    label,
    require,
    shape,
    token_payload,
)


class DeviceVault:
    """Only OS credential storage. Never selects an automatic/file fallback."""

    def __init__(self, origin):
        self.origin = checked_origin(origin)

    def _backend(self):
        try:
            if sys.platform == "darwin":
                from keyring.backends.macOS import Keyring

                return Keyring()
            if sys.platform == "win32":
                from keyring.backends.Windows import WinVaultKeyring

                return WinVaultKeyring()
        except Exception:
            pass
        raise AccessError()

    def _account(self, license_id, device_id):
        return hashlib.sha256(
            (self.origin + "|" + str(license_id) + "|" + device_id).encode()
        ).hexdigest()

    def load(self, license_id, device_id):
        try:
            value = self._backend().get_password(
                "org.aira.device-key.v1", self._account(license_id, device_id)
            )
            if value is None:
                return None
            hex_text(value)
            return bytes.fromhex(value)
        except AccessError:
            raise
        except Exception:
            raise AccessError() from None

    def save(self, license_id, device_id, private_key):
        try:
            require(type(private_key) is bytes and len(private_key) == 32)
            self._backend().set_password(
                "org.aira.device-key.v1", self._account(license_id, device_id), private_key.hex()
            )
        except Exception:
            raise AccessError() from None


class AccessTransport:
    def __init__(self, origin):
        self.origin = checked_origin(origin)

    def execute(self, operation, body, checkpoint):
        require(operation in {"challenge", "complete"})
        checkpoint()
        try:
            with httpx.Client(
                verify=True,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(3.0, pool=0.5),
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            ) as http:
                with http.stream(
                    "POST",
                    self.origin + "/license/model/v1/" + operation,
                    content=canonical(body),
                    headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
                ) as reply:
                    checkpoint()
                    require(reply.status_code in {200, 403, 503})
                    require(
                        reply.headers.get("content-type", "").lower().replace(" ", "")
                        in {"application/json", "application/json;charset=utf-8"}
                    )
                    require(reply.headers.get("content-encoding", "identity") == "identity")
                    require(reply.headers.get("cache-control", "").lower() == "no-store")
                    length = reply.headers.get("content-length")
                    require(
                        length is None
                        or (
                            length.isascii()
                            and length.isdecimal()
                            and len(length) <= 5
                            and int(length) <= 8192
                        )
                    )
                    raw = bytearray()
                    for chunk in reply.iter_raw(chunk_size=1024):
                        checkpoint()
                        require(len(raw) + len(chunk) <= 8192)
                        raw.extend(chunk)
                    require(length is None or len(raw) == int(length))
                    checkpoint()
                    value = decode(bytes(raw))
                    if reply.status_code != 200:
                        shape(value, "code")
                        if reply.status_code == 403 and value["code"] == "enrollment_required":
                            raise AccessError("enrollment_required")
                        raise AccessError()
                    return value
        except AccessError:
            raise
        except Exception:
            raise AccessError() from None


class ModelAccessClient:
    def __init__(self, origin, release_id, manifest_sha256, *, vault=None, transport=None):
        label(release_id)
        hex_text(manifest_sha256)
        self.release_id, self.digest = release_id, manifest_sha256
        self.vault = DeviceVault(origin) if vault is None else vault
        self.transport = AccessTransport(origin) if transport is None else transport

    def unlock(self, permit, *, device_id, license_key=None, checkpoint):
        checkpoint()
        raw = self.vault.load(permit.license_id, device_id)
        checkpoint()
        if raw is None:
            if license_key is None:
                raise AccessError("enrollment_required")
            private = Ed25519PrivateKey.generate()
            raw = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
            checkpoint()
            self.vault.save(permit.license_id, device_id, raw)
            checkpoint()
        require(type(raw) is bytes and len(raw) == 32)
        private = Ed25519PrivateKey.from_private_bytes(raw)
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        operation = "enroll" if license_key is not None else "unlock"
        context = dict(
            schema_version=VERSION,
            operation=operation,
            license_id=str(permit.license_id),
            license_key=license_key,
            device_id=device_id,
            public_key=public,
            client_nonce=secrets.token_hex(32),
            release_id=self.release_id,
            manifest_sha256=self.digest,
        )
        start = time.monotonic()
        challenge = self.transport.execute("challenge", context, checkpoint)
        shape(challenge, "schema_version token")
        require(challenge["schema_version"] == VERSION)
        payload = token_payload(challenge["token"])
        shape(
            payload,
            "schema_version operation license_id device_id public_key client_nonce "
            "release_id manifest_sha256 nonce issued_ms expires_ms revision",
        )
        require(all(payload[k] == context[k] for k in context if k != "license_key"))
        hex_text(payload["nonce"])
        checkpoint()
        result = self.transport.execute(
            "complete",
            dict(
                schema_version=VERSION,
                token=challenge["token"],
                signature=private.sign(DOMAIN + challenge["token"].encode()).hex(),
            ),
            checkpoint,
        )
        shape(
            result,
            "schema_version license_id device_id client_nonce release_id manifest_sha256 "
            "checked_at_ms expires_at_ms key",
        )
        require(
            all(
                result[k] == context[k]
                for k in (
                    "schema_version",
                    "license_id",
                    "device_id",
                    "client_nonce",
                    "release_id",
                    "manifest_sha256",
                )
            )
        )
        require(type(result["checked_at_ms"]) is int and type(result["expires_at_ms"]) is int)
        require(result["checked_at_ms"] < result["expires_at_ms"] == permit.expires_at_ms)
        require(0 <= time.monotonic() - start <= 15)
        hex_text(result["key"])
        checkpoint()
        return bytes.fromhex(result["key"])
