"""Source-derived structural context, separate from literal engine fragments."""

from hashlib import sha256

from ara.docx_analysis.review._json import encode
from ara.docx_analysis.review._models import PreparedReview, checked, require
from ara.docx_analysis.review._request import base as old_base
from ara.docx_analysis.visible_outline import map_outline_spans


def context(snapshot):
    # Canonical encoding streams dataclasses without copying their source graphs.
    return dict(lists=snapshot.lists, note_references=snapshot.references)


def base(snapshot, provenance, kind):
    common = old_base(snapshot, provenance, kind)
    common["schema_version"] = "docx-review/3"
    if kind == "review_result":
        common["document_context"] = context(snapshot)
    return common


def from_verified(snapshot, provenance, limits):
    require(snapshot.complete, "unsupported_document")
    require(bool(snapshot.fragments), "empty_document")
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
            for f in snapshot.fragments
        ),
        disabled_types=(),
        dismissed=(),
        document_context=context(snapshot),
    )
    wire = base(snapshot, provenance, "review_request") | dict(engine_request=engine)
    encoded = encode(wire, limits.max_wire_bytes)
    return PreparedReview(
        encoded, encode(engine, limits.max_wire_bytes), sha256(encoded).hexdigest()
    )


def prepare_outline_review(data, snapshot, *, provenance, limits=None):
    limits = checked(provenance, limits)
    map_outline_spans(data, snapshot, requests=(), limits=limits.view)
    return from_verified(snapshot, provenance, limits)
