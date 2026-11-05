"""Fixed whole-story compatibility semantics and authoritative source-backed mapping."""

from ara.docx_analysis.compatibility_contexts._models import STYLE_PROFILE
from ara.docx_analysis.compatibility_contexts._read import prepare
from ara.docx_analysis.visible_main._build import valid_identity
from ara.docx_analysis.visible_main._map import _map_spans
from ara.docx_analysis.visible_main._models import (
    VisibleSpanRequest,
    VisibleViewError,
    checked_limits,
)
from ara.docx_analysis.visible_notes._build import build
from ara.docx_analysis.visible_notes._shape import validate as validate_notes

from ._failed import failed
from ._provider import Provider
from ._reader import SourceReader

PROFILE = "docx-analysis/final-visible-compatibility-v1"


def build_compatibility_snapshot(
    data, *, document_id, storage_revision, source_sha256, limits=None
):
    return _build_snapshot(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        reader_type=SourceReader,
        profile=PROFILE,
    )


def _build_snapshot(
    data, *, document_id, storage_revision, source_sha256, limits, reader_type, profile
):
    limits = checked_limits(limits)
    if type(data) is not bytes or not valid_identity(document_id, storage_revision, source_sha256):
        raise VisibleViewError("invalid_input")
    prepared = prepare(data, source_sha256=source_sha256, limits=limits)
    if prepared.contexts.status == "blocked":
        return failed(prepared, document_id, storage_revision, limits, profile)
    return build(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        profile=profile,
        reader_type=reader_type,
        provider=Provider(prepared),
    )


def validate(snapshot, limits):
    return validate_notes(snapshot, limits, profile=PROFILE, style_profile=STYLE_PROFILE)


def map_compatibility_spans(data, snapshot, *, requests, limits=None):
    return _map_spans(
        data,
        snapshot,
        requests=requests,
        limits=limits,
        builder=build_compatibility_snapshot,
        validator=validate,
    )


def map_compatibility_span(data, snapshot, *, fragment_id, start, end, quote, limits=None):
    return map_compatibility_spans(
        data,
        snapshot,
        requests=(VisibleSpanRequest(fragment_id, start, end, quote),),
        limits=limits,
    )[0]
