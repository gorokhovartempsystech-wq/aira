"""C2 synthetic pack bytes; no model download, ONNX import or quality claim."""

import importlib
import json
from hashlib import sha256

import pytest


def api():
    return importlib.import_module("ara.docx_analysis_worker.model_input")


def fixture():
    payloads = {
        folder + "/" + name: b"SYNTHETIC-PRIVATE-BYTES"
        for folder in ("embedder", "pair", "nli")
        for name in ("model.int8.onnx", "tokenizer.json")
    }
    manifest = dict(
        name="aira-models",
        version="synthetic-1",
        built="synthetic",
        runtime="CPU synthetic",
        models={
            "embedder": {"license": "Synthetic", "dim": 8},
            "pair": {
                "license": "Synthetic",
                "labels": ["keep", "unrelated", "update", "contradiction"],
                "temperature": 1.0,
            },
            "nli": {"license": "Synthetic", "labels": ["entailment", "neutral", "contradiction"]},
        },
        files={p: {"bytes": len(b), "sha256": sha256(b).hexdigest()} for p, b in payloads.items()},
        total_mb=round(sum(map(len, payloads.values())) / 1e6, 1),
    )
    return manifest, payloads


def raw(manifest):
    return json.dumps(manifest, ensure_ascii=False).encode()


def verify(manifest, files):
    data = raw(manifest)
    return api().verify_pack(data, files, expected_sha256=sha256(data).hexdigest())


def reject(fn, code="model_unavailable"):
    with pytest.raises(api().ModelInputError) as error:
        fn()
    assert error.value.code == code
    assert "PRIVATE" not in str(error.value) and "PRIVATE" not in repr(error.value)


def test_verified_pack_has_exact_immutable_payloads_and_safe_repr():
    m, files = fixture()
    pack = verify(m, files)
    assert pack.models_version == "synthetic-1"
    assert pack.sha256 == sha256(raw(m)).hexdigest()
    assert dict(pack.files) == files
    assert "PRIVATE" not in repr(pack)
    with pytest.raises(TypeError):
        pack.files["nli/model.int8.onnx"] = b"changed"
    files["nli/model.int8.onnx"] = b"changed"
    assert pack.files["nli/model.int8.onnx"] == b"SYNTHETIC-PRIVATE-BYTES"


@pytest.mark.parametrize("kind", ["manifest", "payload", "missing", "extra", "mutable", "size"])
def test_exact_manifest_and_payload_integrity(kind):
    m, files = fixture()
    if kind == "manifest":
        reject(lambda: api().verify_pack(raw(m), files, expected_sha256="0" * 64))
        return
    name = "pair/model.int8.onnx"
    if kind == "payload":
        files[name] = b"x" * len(files[name])
    if kind == "missing":
        del files[name]
    if kind == "extra":
        files["nli/config.json"] = b"{}"
    if kind == "mutable":
        files[name] = bytearray(files[name])
    if kind == "size":
        m["files"][name]["bytes"] += 1
    reject(lambda: verify(m, files))


@pytest.mark.parametrize(
    "path",
    [
        "../secrets.env",
        "/nli/model.int8.onnx",
        "nli/../model.int8.onnx",
        "nli\\model.int8.onnx",
        "NLI/model.int8.onnx",
        "nli/a/model.int8.onnx",
        "nli/secret.txt",
    ],
)
def test_paths_are_closed_names_not_filesystem_requests(path):
    m, files = fixture()
    files[path] = files.pop("nli/model.int8.onnx")
    m["files"][path] = m["files"].pop("nli/model.int8.onnx")
    reject(lambda: verify(m, files))


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "other"),
        ("version", ""),
        ("version", True),
        ("version", "x" * 129),
        ("total_mb", True),
        ("total_mb", -1),
        ("total_mb", 10),
        ("built", None),
        ("runtime", ""),
    ],
)
def test_invalid_manifest_metadata(field, value):
    m, files = fixture()
    m[field] = value
    reject(lambda: verify(m, files))


@pytest.mark.parametrize("kind", ["nli_order", "pair_duplicate", "temperature", "license", "dim"])
def test_model_metadata_is_checked(kind):
    m, files = fixture()
    if kind == "nli_order":
        m["models"]["nli"]["labels"].reverse()
    if kind == "pair_duplicate":
        m["models"]["pair"]["labels"] = ["keep"] * 4
    if kind == "temperature":
        m["models"]["pair"]["temperature"] = 0
    if kind == "license":
        m["models"]["nli"]["license"] = ""
    if kind == "dim":
        m["models"]["embedder"]["dim"] = True
    reject(lambda: verify(m, files))


@pytest.mark.parametrize(
    "data",
    [
        b'{"name":"x","name":"y"}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b"\xff",
        b"[" * 17 + b"0" + b"]" * 17,
        b" " * 1048577,
    ],
)
def test_strict_bounded_json(data):
    reject(lambda: api().verify_pack(data, {}, expected_sha256=sha256(data).hexdigest()))


def test_optional_tokenizer_config_is_integrity_checked():
    m, files = fixture()
    files["embedder/tokenizer_config.json"] = b"{}"
    m["files"]["embedder/tokenizer_config.json"] = {"bytes": 2, "sha256": sha256(b"{}").hexdigest()}
    assert verify(m, files).files["embedder/tokenizer_config.json"] == b"{}"


@pytest.mark.parametrize("size", [True, -1, 536870913])
def test_declared_file_budget_rejected_before_payload(size):
    m, files = fixture()
    m["files"]["nli/model.int8.onnx"]["bytes"] = size
    reject(lambda: verify(m, files))
