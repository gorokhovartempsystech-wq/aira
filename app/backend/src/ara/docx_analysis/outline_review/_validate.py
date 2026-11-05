"""Structured results use the same atomic evidence algorithm with a fixed new source."""

from ara.docx_analysis.review._validate import validate_reply
from ara.docx_analysis.visible_outline import map_outline_spans

from ._request import base, from_verified


def validate_outline_reply(data, snapshot, *, provenance, request, reply, limits=None):
    return validate_reply(
        data,
        snapshot,
        provenance=provenance,
        request=request,
        reply=reply,
        limits=limits,
        mapper=map_outline_spans,
        request_factory=from_verified,
        base_factory=base,
    )
