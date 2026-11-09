import hashlib
import json

import pytest

from aira_ml.verify_pack import verify


def pack(tmp_path):
    files = {}
    for model in ("embedder", "pair", "nli"):
        for name in ("model.int8.onnx", "tokenizer.json"):
            path = tmp_path / model / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"example")
            files[f"{model}/{name}"] = {
                "bytes": 7, "sha256": hashlib.sha256(b"example").hexdigest()
            }
    manifest = {"version": "test", "files": files}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_valid_pack(tmp_path):
    pack(tmp_path)
    assert verify(tmp_path) == "test"


def test_corruption_even_same_size(tmp_path):
    pack(tmp_path)
    (tmp_path / "nli/model.int8.onnx").write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA256"):
        verify(tmp_path)


def test_incomplete_manifest(tmp_path):
    manifest = pack(tmp_path)
    del manifest["files"]["nli/model.int8.onnx"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="omits"):
        verify(tmp_path)


def test_manifest_escape(tmp_path):
    manifest = pack(tmp_path)
    manifest["files"]["../outside"] = {"bytes": 0, "sha256": ""}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="escapes"):
        verify(tmp_path)
