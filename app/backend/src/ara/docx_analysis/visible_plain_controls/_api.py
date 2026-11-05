"""Fixed plain-control profile; every mapping batch rebuilds authoritative source facts."""

from ara.docx_analysis.compatibility_contexts._models import STYLE_PROFILE
from ara.docx_analysis.visible_compatibility._api import _build_snapshot
from ara.docx_analysis.visible_main._map import _map_spans
from ara.docx_analysis.visible_main._models import VisibleSpanRequest
from ara.docx_analysis.visible_notes._shape import validate as validate_notes

from ._reader import PlainReader

PROFILE = "docx-analysis/final-visible-plain-controls-v1"


def build_plain_control_snapshot(
    data, *, document_id, storage_revision, source_sha256, limits=None
):
    return _build_snapshot(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        reader_type=PlainReader,
        profile=PROFILE,
    )


def validate(snapshot, limits):
    return validate_notes(snapshot, limits, profile=PROFILE, style_profile=STYLE_PROFILE)


def map_plain_control_spans(data, snapshot, *, requests, limits=None):
    return _map_spans(
        data,
        snapshot,
        requests=requests,
        limits=limits,
        builder=build_plain_control_snapshot,
        validator=validate,
    )


def map_plain_control_span(data, snapshot, *, fragment_id, start, end, quote, limits=None):
    return map_plain_control_spans(
        data,
        snapshot,
        requests=(VisibleSpanRequest(fragment_id, start, end, quote),),
        limits=limits,
    )[0]
