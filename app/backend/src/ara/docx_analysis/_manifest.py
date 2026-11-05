"""Deterministic hashes over explicit internal DTO fields, never logged."""

import json
from hashlib import sha256

from ara.docx_package.projection import SourceAnchor

from ._models import AnalysisSnapshot


def digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def anchor_json(anchor: SourceAnchor | None) -> dict | None:
    if anchor is None:
        return None
    return {
        "source_sha256": anchor.source_sha256,
        "part_name": anchor.part_name,
        "path": list(anchor.path),
    }


def fragment_id(anchor: SourceAnchor) -> str:
    return "f-" + digest({"domain": "docx-analysis-fragment/1", **anchor_json(anchor)})


def manifest_digest(snapshot: AnalysisSnapshot) -> str:
    return digest(
        {
            "document_id": str(snapshot.document_id),
            "storage_revision": str(snapshot.storage_revision),
            "source_sha256": snapshot.source_sha256,
            "extractor_version": snapshot.extractor_version,
            "main_part": snapshot.main_part,
            "body_anchor": anchor_json(snapshot.body_anchor),
            "fragments": [
                {
                    "fragment_id": f.fragment_id,
                    "paragraph_anchor": anchor_json(f.paragraph_anchor),
                    "ancestry": [anchor_json(a) for a in f.ancestry],
                    "text": f.text,
                    "analysis_start": f.analysis_start,
                    "analysis_end": f.analysis_end,
                    "segments": [
                        {
                            "kind": s.kind,
                            "anchor": anchor_json(s.anchor),
                            "run_anchor": anchor_json(s.run_anchor),
                            "start": s.start,
                            "end": s.end,
                        }
                        for s in f.segments
                    ],
                }
                for f in snapshot.fragments
            ],
            "analysis_text": snapshot.analysis_text,
            "coverage": [
                {
                    "status": c.status,
                    "code": c.code,
                    "part_name": c.part_name,
                    "anchor": anchor_json(c.anchor),
                    "fragment_id": c.fragment_id,
                }
                for c in snapshot.coverage
            ],
            "has_unprojected_content": snapshot.has_unprojected_content,
            "complete": snapshot.complete,
            "text_sha256": snapshot.text_sha256,
        }
    )
