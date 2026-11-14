"""Closed, bounded model-access messages; no environment or I/O on import."""

import base64
import hashlib
import hmac
import json
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

VERSION = "aira-model-access/1"
DOMAIN = b"aira-model-proof/1\x00"
MAX_BODY = 8192


class AccessError(Exception):
    def __init__(self, code="model_access_unavailable"):
        self.code = (
            code
            if code in {"enrollment_required", "model_access_unavailable"}
            else "model_access_unavailable"
        )
        super().__init__(self.code)


def require(condition):
    if not condition:
        raise AccessError()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def decode(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BODY)
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, RecursionError, TypeError):
        raise AccessError() from None
    require(type(value) is dict)
    return value


def shape(value, names):
    require(type(value) is dict and set(value) == set(names.split()))


def hex_text(value, length=64):
    require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value) is not None
    )
    return value


def label(value):
    require(
        type(value) is str and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}", value) is not None
    )
    return value


def token_payload(token):
    require(type(token) is str and len(token) <= 4096 and token.count(".") == 1)
    payload, tag = token.split(".")
    hex_text(tag)
    try:
        raw = base64.b64decode(payload, altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise AccessError() from None
    require(base64.urlsafe_b64encode(raw).decode() == payload)
    value = decode(raw)
    require(canonical(value) == raw)
    return value


def make_token(value, pepper):
    body = base64.urlsafe_b64encode(canonical(value)).decode()
    tag = hmac.digest(pepper, DOMAIN + body.encode(), hashlib.sha256).hex()
    return body + "." + tag


def verify_token(token, pepper):
    value = token_payload(token)
    require(hmac.compare_digest(make_token(value, pepper), token))
    return value


def verify_proof(public_key, token, signature):
    hex_text(public_key)
    hex_text(signature, 128)
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(
            bytes.fromhex(signature), DOMAIN + token.encode()
        )
    except Exception:
        raise AccessError() from None
