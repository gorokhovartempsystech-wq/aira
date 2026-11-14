"""Explicit local ONNX adapter for Word requests; never substitutes a fixture."""

import base64
import hashlib
import json
import sys
import time
from pathlib import Path

from ara.docx_analysis.storage_codec import ExecutionSpec
from ara.docx_analysis.visible_word._models import PROFILE

from .prototype import propose
from .review_fixture import _fragments, _request_header
from .wire import encode_message


def require(ok):
    if not ok:
        raise ValueError("Invalid local model input or package")


def package_identity(model_dir, engine_dir, *, checkpoint=None):
    root = Path(model_dir).resolve()
    raw = (root / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    require(type(manifest.get("files")) is dict and bool(manifest["files"]))
    for name, expected in manifest["files"].items():
        if checkpoint is not None:
            checkpoint()
        path = (root / name).resolve()
        require(path.is_relative_to(root) and path.is_file())
        require(path.stat().st_size == expected["bytes"])
        with path.open("rb") as handle:
            if checkpoint is None:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            else:
                hashed = hashlib.sha256()
                while chunk := handle.read(1024 * 1024):
                    checkpoint()
                    hashed.update(chunk)
                checkpoint()
                digest = hashed.hexdigest()
        require(digest == expected["sha256"])
    runtime = Path(engine_dir) / "aira_ml"
    adapter = hashlib.sha256(Path(__file__).read_bytes())
    for name in ("engine.py", "lint.py", "stable_nli.py"):
        if name == "stable_nli.py" and not (runtime / name).exists():
            continue
        adapter.update(name.encode())
        adapter.update((runtime / name).read_bytes())
    for path in sorted(Path(__file__).with_name("prototype").glob("*.py")):
        adapter.update(path.name.encode())
        adapter.update(path.read_bytes())
    if "protection" in manifest:
        from ara.model_protection.bundle import configuration

        require(configuration(root) is not None)
        for path in sorted((Path(__file__).parents[1] / "model_protection").glob("*.py")):
            adapter.update(path.name.encode())
            adapter.update(path.read_bytes())
    return ExecutionSpec(
        "local_model",
        "0.1.0",
        manifest["version"],
        hashlib.sha256(raw).hexdigest(),
        adapter.hexdigest(),
    )


def adapt(raw, *, questions=()):
    require(
        type(raw) is dict
        and set(raw) == {"engine", "models", "issues", "questions", "checked", "seconds", "partial"}
    )
    checked = raw["checked"]
    require(
        type(checked) is dict
        and set(checked) == {"fragments", "active", "skipped_status", "pairwise"}
    )
    require(all(type(v) is int and v >= 0 for v in checked.values()))
    require(checked["pairwise"] <= checked["active"] <= checked["fragments"])
    partial = raw["partial"]
    require(partial is None or (type(partial) is str and bool(partial.strip())))
    result = {k: v for k, v in raw.items() if k != "partial"}
    result["checked"] = {k: v for k, v in checked.items() if k != "pairwise"}
    checks = ["formulation", "duplicate", "contradiction"]
    result["extensions"] = dict(
        schema_version="aira-review-extensions/1",
        analysis_coverage=dict(
            state="partial" if partial else "complete",
            reason="deadline" if partial else None,
            planned_checks=checks,
            completed_checks=checks[:2] if partial else checks,
            pair_selection="top_k",
            pair_candidates_total=None,
            pair_candidates_completed=None,
        ),
        standalone_questions=list(questions),
    )
    return json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def run(request, *, model_dir, engine_dir, emit, budget_seconds=285, model_key=None):
    require(type(budget_seconds) in (int, float) and 0 < budget_seconds <= 290)
    deadline = time.monotonic() + budget_seconds
    spec = package_identity(model_dir, engine_dir)
    _, body = _request_header(request, spec)
    require((body["schema_version"], body["profile"]) == ("docx-review/5", PROFILE))
    fragments = _fragments(
        body["engine_request"],
        keys="fragments disabled_types dismissed document_context",
    )

    def send(kind, seq, **values):
        emit(encode_message(request.binding, kind=kind, seq=seq, values=values))

    send("ready", 0, execution_spec_sha256=request.values["execution_spec_sha256"])
    send("stage", 1, stage="loading_model")
    from aira_ml.engine import Engine

    from ara.model_protection.bundle import ModelReader, configuration

    if configuration(model_dir) is not None:
        model = Engine(model_dir, threads=6, model_reader=ModelReader(model_dir, model_key))
    else:
        require(model_key is None)
        model = Engine(model_dir, threads=6)
    require(model.manifest["version"] == spec.models_version)
    calls = {"embedder": 0, "nli": 0}

    def counted(name, original):
        def invoke(*args, **kwargs):
            calls[name] += 1
            return original(*args, **kwargs)

        return invoke

    model.emb.run = counted("embedder", model.emb.run)
    model.nli.run = counted("nli", model.nli.run)
    require(time.monotonic() < deadline)
    send("stage", 2, stage="analyzing")
    raw = model.review(fragments, deadline=time.time() + max(0, deadline - time.monotonic()))
    print(json.dumps({"onnx_calls": calls}), file=sys.stderr, flush=True)
    result = adapt(raw, questions=propose(fragments))
    require(time.monotonic() < deadline + 5)
    send(
        "result",
        3,
        reply_sha256=hashlib.sha256(result).hexdigest(),
        reply_b64=base64.b64encode(result).decode("ascii"),
    )
