"""Versioned extension of the pinned review validator; source checks stay intact."""

import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ara.docx_analysis.review import ReviewProvenance, prepare_review, validate_engine_reply
from ara.docx_analysis.visible_main import build_visible_snapshot


def review_saved(data, document_id, revision, model, *, deadline=None):
    snapshot = build_visible_snapshot(
        data,
        document_id=document_id,
        storage_revision=revision,
        source_sha256=sha256(data).hexdigest(),
    )
    provenance = ReviewProvenance(
        attempt_id=uuid4(),
        execution_kind="local_model",
        engine_version="0.1.0",
        models_version=model.manifest["version"],
        model_sha256=sha256((model.dir / "manifest.json").read_bytes()).hexdigest(),
        adapter_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    request = prepare_review(data, snapshot, provenance=provenance)
    args = json.loads(request.engine_request_json)
    raw = model.review(args["fragments"], deadline=deadline)
    return adapt_reply(data, snapshot, provenance, request, raw)


def adapt_reply(data, snapshot, provenance, request, raw):
    # Accept exactly the current extension; never silently drop unknown fields.
    if set(raw) != {"engine", "models", "issues", "questions", "checked", "seconds", "partial"}:
        raise ValueError("Unsupported engine reply")
    checked = raw["checked"]
    if set(checked) != {"fragments", "active", "skipped_status", "pairwise"}:
        raise ValueError("Unsupported coverage")
    partial = raw["partial"]
    if partial is not None and (
        type(partial) is not str or not partial.strip() or len(partial) > 4096
    ):
        raise ValueError("Invalid partial reason")
    pairwise = checked["pairwise"]
    if type(pairwise) is not int or not 0 <= pairwise <= checked["active"]:
        raise ValueError("Invalid pairwise coverage")
    canonical = {k: v for k, v in raw.items() if k != "partial"}
    canonical["checked"] = {k: v for k, v in checked.items() if k != "pairwise"}
    validated = validate_engine_reply(
        data,
        snapshot,
        provenance=provenance,
        request=request,
        reply=json.dumps(canonical, ensure_ascii=False).encode(),
    )
    result = json.loads(validated.wire_json)
    result["no_findings"] = result["no_findings"] and partial is None
    return {
        "schema_version": "local-model-review/1",
        "result": result,
        "incomplete": partial is not None,
        "partial_reason": partial,
        "checked": checked,
        "seconds": raw["seconds"],
        "coverage_note": (
            "Попарно проверяются похожие фрагменты; все возможные пары не перебираются."
        ),
    }
