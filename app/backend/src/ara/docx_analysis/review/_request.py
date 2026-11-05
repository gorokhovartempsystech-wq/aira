"""Exact engine fragments derived from a verified, complete saved snapshot."""

from dataclasses import fields
from hashlib import sha256

from ara.docx_analysis.visible_main import map_visible_spans

from ._json import encode
from ._models import VERSION, PreparedReview, checked, require


def source_identity(s):
    return dict(
        document_id=str(s.document_id),
        storage_revision=str(s.storage_revision),
        source_sha256=s.source_sha256,
    )


def provenance_dict(p):
    return {
        f.name: str(p.attempt_id) if f.name == "attempt_id" else getattr(p, f.name)
        for f in fields(p)
    }


def base(s, p, kind):
    return dict(
        schema_version=VERSION,
        kind=kind,
        source=source_identity(s),
        snapshot_sha256=s.snapshot_sha256,
        profile=s.profile,
        policy_version=s.policy_version,
        provenance=provenance_dict(p),
    )


def from_verified(s, p, limits):
    require(s.complete, "unsupported_document")
    require(bool(s.fragments), "empty_document")
    engine = dict(
        fragments=tuple(
            dict(
                id=f.fragment_id,
                text=f.text,
                document="Документ",
                status="active",
                type="фрагмент",
                offset=f.analysis_start,
            )
            for f in s.fragments
        ),
        disabled_types=(),
        dismissed=(),
    )
    wire = base(s, p, "review_request") | dict(engine_request=engine)
    encoded = encode(wire, limits.max_wire_bytes)
    return PreparedReview(
        encoded, encode(engine, limits.max_wire_bytes), sha256(encoded).hexdigest()
    )


def prepare_review(data, snapshot, *, provenance, limits=None):
    limits = checked(provenance, limits)
    map_visible_spans(data, snapshot, requests=(), limits=limits.view)
    return from_verified(snapshot, provenance, limits)


def check_prepared(request, limits):
    require(type(request) is PreparedReview, "invalid_input")
    for name in ("wire_json", "engine_request_json"):
        raw = getattr(request, name, None)
        require(type(raw) is bytes, "invalid_input")
        require(len(raw) <= limits.max_wire_bytes, "review_limit_exceeded")
    digest = getattr(request, "request_sha256", None)
    require(type(digest) is str and len(digest) == 64, "invalid_input")
