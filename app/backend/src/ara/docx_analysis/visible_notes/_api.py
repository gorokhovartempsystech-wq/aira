"""Fixed note-story profile and one authoritative original-source rebuild per batch."""

from ara.docx_analysis.visible_main._map import _map_spans
from ara.docx_analysis.visible_main._models import VisibleSpanRequest

from ._build import build
from ._shape import validate


def build_note_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None):
    return build(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
    )


def map_note_spans(data, snapshot, *, requests, limits=None):
    return _map_spans(
        data,
        snapshot,
        requests=requests,
        limits=limits,
        builder=build_note_snapshot,
        validator=validate,
    )


def map_note_span(data, snapshot, *, fragment_id, start, end, quote, limits=None):
    return map_note_spans(
        data,
        snapshot,
        requests=(VisibleSpanRequest(fragment_id, start, end, quote),),
        limits=limits,
    )[0]
