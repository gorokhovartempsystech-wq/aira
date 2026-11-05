"""Adapter contract and package integrity; no model downloads or inference."""

import hashlib
import json

import pytest

from ara.docx_analysis_worker.local_model import adapt, package_identity


def raw():
    return dict(
        engine="0.1.0",
        models="0.2m",
        issues=[],
        questions=[],
        checked=dict(fragments=3, active=3, skipped_status=0, pairwise=2),
        partial=None,
        seconds=1.0,
    )


def test_complete_and_unknown_pair_counts():
    r = json.loads(adapt(raw()))
    c = r["extensions"]["analysis_coverage"]
    assert c["state"] == "complete" and c["pair_candidates_total"] is None
    assert "pairwise" not in r["checked"] and "partial" not in r
    assert r["extensions"]["standalone_questions"] == []


def test_partial_never_claims_complete_logic():
    data = raw() | {"partial": "не хватило времени"}
    c = json.loads(adapt(data))["extensions"]["analysis_coverage"]
    assert c["state"] == "partial" and c["reason"] == "deadline"
    assert "contradiction" not in c["completed_checks"]


@pytest.mark.parametrize("patch", [{"unexpected": 1}, {"partial": ""}, {"partial": True}])
def test_unknown_or_invalid_reply_rejected(patch):
    with pytest.raises(ValueError):
        adapt(raw() | patch)


@pytest.mark.parametrize("value", [True, -1, 4, "2"])
def test_invalid_pairwise_rejected(value):
    data = raw()
    data["checked"]["pairwise"] = value
    with pytest.raises(ValueError):
        adapt(data)


def test_package_tamper_fails_before_load(tmp_path):
    runtime = tmp_path / "runtime" / "aira_ml"
    runtime.mkdir(parents=True)
    for name in ("engine.py", "lint.py"):
        (runtime / name).write_text("# synthetic")
    model = tmp_path / "models"
    model.mkdir()
    data = b"synthetic model bytes"
    (model / "model.onnx").write_bytes(data)
    manifest = dict(
        version="test",
        files={"model.onnx": dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())},
    )
    (model / "manifest.json").write_text(json.dumps(manifest))
    spec = package_identity(model, runtime.parent)
    assert spec.execution_kind == "local_model"
    (model / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        package_identity(model, runtime.parent)


def test_stable_nli_code_changes_execution_identity(tmp_path):
    runtime = tmp_path / "runtime" / "aira_ml"
    runtime.mkdir(parents=True)
    for name in ("engine.py", "lint.py", "stable_nli.py"):
        (runtime / name).write_text("# synthetic v1")
    model = tmp_path / "models"
    model.mkdir()
    data = b"synthetic model bytes"
    (model / "model.onnx").write_bytes(data)
    manifest = dict(
        version="test",
        files={"model.onnx": dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())},
    )
    (model / "manifest.json").write_text(json.dumps(manifest))
    before = package_identity(model, runtime.parent)
    (runtime / "stable_nli.py").write_text("# synthetic v2")
    after = package_identity(model, runtime.parent)
    assert before.model_sha256 == after.model_sha256
    assert before.adapter_sha256 != after.adapter_sha256
