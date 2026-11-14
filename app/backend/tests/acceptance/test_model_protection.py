"""Synthetic model bytes and ephemeral keys only; no real weights or credentials."""

import json
import struct
from secrets import token_bytes

import pytest

from ara import model_protection as api


def inputs():
    return b"SYNTHETIC_ONNX_MODEL_PRIVATE_CONTENT" * 8, token_bytes(32)


def seal(data, key):
    return api.seal_model(data, key, model_id="nli", version="0.2m")


def open_(data, key, **kwargs):
    return api.open_model(data, key, **(dict(model_id="nli", version="0.2m") | kwargs))


def test_roundtrip_random_nonce_and_no_plaintext_in_container():
    model, key = inputs()
    one, two = seal(model, key), seal(model, key)
    assert one != two
    assert model not in one
    assert open_(one, key) == open_(two, key) == model


def test_no_files_are_created(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    model, key = inputs()
    assert open_(seal(model, key), key) == model
    assert list(tmp_path.iterdir()) == []


def test_wrong_key_and_identity_are_rejected():
    model, key = inputs()
    package = seal(model, key)
    for wrong in (dict(model_id="embedder"), dict(version="0.3")):
        with pytest.raises(api.ModelProtectionError):
            open_(package, key, **wrong)
    with pytest.raises(api.ModelProtectionError):
        open_(package, token_bytes(32))


def test_every_single_byte_tamper_is_rejected():
    model, key = inputs()
    package = seal(model, key)
    for index in range(len(package)):
        changed = bytearray(package)
        changed[index] ^= 1
        with pytest.raises(api.ModelProtectionError):
            open_(bytes(changed), key)


def test_every_truncation_and_appended_data_are_rejected():
    model, key = inputs()
    package = seal(model, key)
    for index in range(len(package)):
        with pytest.raises(api.ModelProtectionError):
            open_(package[:index], key)
    with pytest.raises(api.ModelProtectionError):
        open_(package + b"extra", key)


@pytest.mark.parametrize("bad", [None, True, "key", b"", b"x" * 16, b"x" * 33, bytearray(32)])
def test_keys_have_exact_type_and_size(bad):
    with pytest.raises(api.ModelProtectionError):
        seal(b"model", bad)
    with pytest.raises(api.ModelProtectionError):
        open_(b"package", bad)


@pytest.mark.parametrize("bad", ["", "../nli", "a/b", "a\\b", "a\n", "a" * 97, 1, None])
def test_unsafe_ids_are_rejected(bad):
    with pytest.raises(api.ModelProtectionError):
        api.seal_model(b"model", token_bytes(32), model_id=bad, version="0.2m")


def test_declared_size_is_bounded_before_decryption(monkeypatch):
    model, key = inputs()
    package = seal(model, key)
    monkeypatch.setattr(api, "MAX_MODEL_BYTES", 10)
    with pytest.raises(api.ModelProtectionError):
        open_(package, key)
    with pytest.raises(api.ModelProtectionError):
        seal(model, key)


def test_malicious_headers_have_safe_errors():
    _, key = inputs()
    prefix = api.MAGIC
    headers = [
        b"[1]",
        b"{}",
        b"{",
        b"\xff",
        b"[" * 200,
        b'{"model_id":"nli","model_id":"nli","size":1,"version":"0.2m"}',
    ]
    for header in headers:
        package = prefix + struct.pack(">I", len(header)) + header + b"x" * 100
        with pytest.raises(api.ModelProtectionError):
            open_(package, key)
    with pytest.raises(api.ModelProtectionError):
        open_(prefix + struct.pack(">I", 2**32 - 1) + b"x" * 100, key)


def test_errors_do_not_expose_sensitive_values():
    model, key = inputs()
    with pytest.raises(api.ModelProtectionError) as caught:
        open_(seal(model, key), token_bytes(32))
    rendered = str(caught.value) + repr(caught.value)
    assert model.decode() not in rendered and key.hex() not in rendered


def test_noncanonical_authenticated_header_rejected_even_with_valid_tag():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    model, key = inputs()
    header = json.dumps(dict(model_id="nli", version="0.2m", size=len(model))).encode()
    prefix = api.MAGIC + struct.pack(">I", len(header)) + header
    nonce = token_bytes(12)
    package = prefix + nonce + AESGCM(key).encrypt(nonce, model, prefix)
    with pytest.raises(api.ModelProtectionError):
        open_(package, key)
