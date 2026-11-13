"""Synthetic model containers; no release secrets or customer documents."""

import hashlib
import json
import secrets

import pytest

from ara.model_protection import ModelProtectionError
from ara.model_protection.access_wire import AccessError
from ara.model_protection.bundle import ModelReader, configuration, pack


def source(root):
    data = {
        "embedder/model.int8.onnx": b"SYNTHETIC_MODEL_BYTES",
        "embedder/tokenizer.json": b'{"synthetic":true}',
    }
    files = {}
    for name, raw in data.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        files[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    (root / "manifest.json").write_text(json.dumps(dict(version="synthetic", files=files)))
    return data


def test_only_ciphertext_and_declared_tokenizer_assets_are_packaged(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    data, key = source(old), secrets.token_bytes(32)
    (old / "undeclared.onnx").write_bytes(b"MUST_NOT_SHIP")
    release, digest = pack(old, new, key, release_id="release-1")
    assert release == "release-1" and digest == configuration(new)[1]
    assert not list(new.rglob("*.onnx"))
    assert len(list(new.rglob("*.aira"))) == 1
    for item in new.rglob("*"):
        if item.is_file():
            raw = item.read_bytes()
            assert data["embedder/model.int8.onnx"] not in raw
            assert key.hex().encode() not in raw
            assert b"MUST_NOT_SHIP" not in raw
    reader = ModelReader(new, key)
    assert reader(new / "embedder/model.int8.onnx") == data["embedder/model.int8.onnx"]
    assert (old / "embedder/model.int8.onnx").read_bytes() == data["embedder/model.int8.onnx"]


def test_wrong_key_tamper_path_escape_and_existing_output_fail_closed(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    source(old)
    key = secrets.token_bytes(32)
    pack(old, new, key, release_id="release-1")
    with pytest.raises(AccessError):
        pack(old, new, key, release_id="release-1")
    with pytest.raises(ModelProtectionError):
        ModelReader(new, secrets.token_bytes(32))(new / "embedder/model.int8.onnx")
    reader = ModelReader(new, key)
    with pytest.raises(AccessError):
        reader(tmp_path / "unrelated/model.int8.onnx")
    target = new / "embedder/model.int8.onnx.aira"
    raw = target.read_bytes()
    target.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(AccessError):
        reader(new / "embedder/model.int8.onnx")
    assert not list(new.rglob("*.onnx"))


def test_bad_source_hash_is_never_published(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    source(old)
    (old / "embedder/model.int8.onnx").write_bytes(b"altered")
    with pytest.raises(AccessError):
        pack(old, new, secrets.token_bytes(32), release_id="release-1")
    assert not new.exists()
