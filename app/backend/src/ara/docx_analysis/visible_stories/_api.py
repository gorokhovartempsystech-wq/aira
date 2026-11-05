"""Fixed section-story profile, one authoritative source rebuild per mapping batch."""

from ara.docx_analysis.visible_main._map import _map_spans
from ara.docx_analysis.visible_main._models import VisibleSpanRequest
from ara.docx_analysis.visible_main._shape import _validate

from ._assemble import PROFILE
from ._build import build


def build_story_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None):
    return build(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
    )


def validate(snapshot, limits):
    return _validate(snapshot, limits, profile=PROFILE)


def map_story_spans(data, snapshot, *, requests, limits=None):
    return _map_spans(
        data,
        snapshot,
        requests=requests,
        limits=limits,
        builder=build_story_snapshot,
        validator=validate,
    )


def map_story_span(data, snapshot, *, fragment_id, start, end, quote, limits=None):
    return map_story_spans(
        data,
        snapshot,
        requests=(VisibleSpanRequest(fragment_id, start, end, quote),),
        limits=limits,
    )[0]
