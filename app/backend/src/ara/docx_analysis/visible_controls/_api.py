"""Fixed rich-control profile and exact original-source batch mapping."""

from ara.docx_analysis.visible_main._map import _map_spans
from ara.docx_analysis.visible_main._models import VisibleSpanRequest
from ara.docx_analysis.visible_notes._build import build
from ara.docx_analysis.visible_notes._shape import validate as validate_notes

from ._parse import preflight
from ._reader import ControlReader

PROFILE = "docx-analysis/final-visible-rich-controls-v1"


def build_control_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None):
    return build(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        reader_type=ControlReader,
        profile=PROFILE,
        extra_preflight=preflight,
    )


def validate(snapshot, limits):
    return validate_notes(snapshot, limits, profile=PROFILE)


def map_control_spans(data, snapshot, *, requests, limits=None):
    return _map_spans(
        data,
        snapshot,
        requests=requests,
        limits=limits,
        builder=build_control_snapshot,
        validator=validate,
    )


def map_control_span(data, snapshot, *, fragment_id, start, end, quote, limits=None):
    return map_control_spans(
        data,
        snapshot,
        requests=(VisibleSpanRequest(fragment_id, start, end, quote),),
        limits=limits,
    )[0]
