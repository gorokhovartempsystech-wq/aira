"""Fixed unlisted profile with fresh source-backed pagination and unused-list proof."""

from functools import partial
from hashlib import sha256

from ara.docx_analysis.compatibility_contexts._read import ERRORS, prepare
from ara.docx_analysis.visible_compatibility._failed import failed
from ara.docx_analysis.visible_compatibility._provider import Provider
from ara.docx_analysis.visible_inline_images._assemble import Output
from ara.docx_analysis.visible_main._build import valid_identity
from ara.docx_analysis.visible_main._map import _map_spans
from ara.docx_analysis.visible_main._models import (
    VisibleSpanRequest,
    VisibleViewError,
    checked_limits,
)
from ara.docx_analysis.visible_notes._build import build
from ara.docx_analysis.visible_notes._shape import validate as validate_notes
from ara.docx_package import DocxError, DocxLimits, open_docx

from ._accounting import Accounting
from ._contexts import CONTEXT_PROFILE, STYLE_PROFILE, pagination_contexts
from ._numbering import preflight
from ._reader import UnlistedReader

PROFILE = "docx-analysis/final-visible-unlisted-v1"


def build_unlisted_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None):
    limits = checked_limits(limits)
    if type(data) is not bytes or not valid_identity(document_id, storage_revision, source_sha256):
        raise VisibleViewError("invalid_input")
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise VisibleViewError("source_mismatch")
    source = open_docx(data)
    try:
        preflight(data, source, bounds, limits)
    except ERRORS as exc:
        code = "view_limit_exceeded" if exc.code.endswith("limit_exceeded") else exc.code
        raise VisibleViewError(code) from None
    prepared = prepare(
        data,
        source_sha256=source_sha256,
        limits=limits,
        context_factory=pagination_contexts,
        context_profile=CONTEXT_PROFILE,
    )
    if prepared.contexts.status == "blocked":
        return failed(
            prepared, document_id, storage_revision, limits, PROFILE, style_profile=STYLE_PROFILE
        )
    root = next(p.root for p in prepared.view.parts if p.part_name == source.main_part)
    media = Accounting(data, source, bounds, limits, root.tag.rpartition("}")[0] + "}")
    return build(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        profile=PROFILE,
        reader_type=partial(UnlistedReader, media=media),
        provider=Provider(prepared),
        output_factory=Output,
        coverage_factory=media.coverage,
    )


def validate(snapshot, limits):
    return validate_notes(snapshot, limits, profile=PROFILE, style_profile=STYLE_PROFILE)


def map_unlisted_spans(data, snapshot, *, requests, limits=None):
    return _map_spans(
        data,
        snapshot,
        requests=requests,
        limits=limits,
        builder=build_unlisted_snapshot,
        validator=validate,
    )


def map_unlisted_span(data, snapshot, *, fragment_id, start, end, quote, limits=None):
    return map_unlisted_spans(
        data,
        snapshot,
        requests=(VisibleSpanRequest(fragment_id, start, end, quote),),
        limits=limits,
    )[0]
