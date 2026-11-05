"""Private continuation of codec proof, scoped to one freshly restored source.

Only storage_codec may call this after restore_source has rebuilt the original
bytes, compared the complete manifest and checked review/admission budgets. There
is no persisted/global cache or caller-supplied verification flag. Public review
and mapping entrypoints still rebuild their untrusted source on every call.
"""

from ara.docx_analysis.review._models import require
from ara.docx_analysis.review._validate import validate_reply
from ara.docx_analysis.visible_main._map import _map_spans
from ara.docx_analysis.visible_word._shape import validate

from ._request import base, from_verified


def capture_restored(data, snapshot, *, provenance, attempt, reply, limits):
    request = from_verified(snapshot, provenance, limits)
    require(
        request.wire_json == attempt.request_data
        and request.request_sha256 == attempt.request_sha256,
        "invalid_input",
    )

    def rebuilt(original, *, document_id, storage_revision, source_sha256, limits):
        # Retain the exact immutable bytes and newly derived DTO for this call
        # only. No incoming detached snapshot is returned by this builder.
        require(
            original is data
            and (document_id, storage_revision, source_sha256)
            == (snapshot.document_id, snapshot.storage_revision, snapshot.source_sha256),
            "invalid_input",
        )
        return snapshot

    def mapper(original, candidate, *, requests, limits):
        require(original is data and candidate is snapshot, "invalid_input")
        return _map_spans(
            original,
            candidate,
            requests=requests,
            limits=limits,
            builder=rebuilt,
            validator=validate,
        )

    return validate_reply(
        data,
        snapshot,
        provenance=provenance,
        request=request,
        reply=reply,
        limits=limits,
        mapper=mapper,
        request_factory=from_verified,
        base_factory=base,
    )
