"""Read the original package, prove full closure, and map only original literal evidence."""

from dataclasses import fields, replace
from functools import partial
from hashlib import sha256

from ara.docx_analysis.visible_compatibility._failed import failed
from ara.docx_analysis.visible_compatibility._provider import Provider
from ara.docx_analysis.visible_lists._assemble import Output
from ara.docx_analysis.visible_main._build import valid_identity
from ara.docx_analysis.visible_main._canonical import digest
from ara.docx_analysis.visible_main._map import _map_spans
from ara.docx_analysis.visible_main._models import (
    VisibleSpanRequest,
    VisibleViewError,
    checked_limits,
)
from ara.docx_analysis.visible_notes import NoteSnapshot
from ara.docx_analysis.visible_notes._build import build
from ara.docx_package import DocxError, DocxLimits, open_docx

from ._auxiliary import Accounting
from ._models import PROFILE, STYLE_PROFILE, WordSnapshot
from ._numbering import State
from ._reader import Reader
from ._selected import prepare
from ._shape import validate


def extended(base, items, limits):
    result = WordSnapshot(
        **{f.name: getattr(base, f.name) for f in fields(NoteSnapshot)},
        lists=tuple(items) if base.complete else (),
    )
    return replace(
        result, snapshot_sha256=digest(result, limits.max_manifest_bytes, omit_hash=True)
    )


def build_word_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None):
    limits = checked_limits(limits)
    if type(data) is not bytes or not valid_identity(document_id, storage_revision, source_sha256):
        raise VisibleViewError("invalid_input")
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise VisibleViewError("source_mismatch")
    source = open_docx(data)
    prepared = prepare(data, source, bounds, limits)
    if prepared.contexts.status == "blocked":
        return extended(
            failed(
                prepared,
                document_id,
                storage_revision,
                limits,
                PROFILE,
                style_profile=STYLE_PROFILE,
            ),
            (),
            limits,
        )
    root = next(p.root for p in prepared.view.parts if p.part_name == source.main_part)
    lists = State(data, source, bounds, root.tag.rpartition("}")[0] + "}", limits, prepared)
    media = Accounting(data, source, bounds, limits, lists, prepared)
    base = build(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        profile=PROFILE,
        reader_type=partial(Reader, media=media, lists=lists),
        provider=Provider(prepared),
        output_factory=partial(Output, lists=lists),
        coverage_factory=media.coverage,
    )
    return extended(base, lists.items, limits)


def map_word_spans(data, snapshot, *, requests, limits=None):
    return _map_spans(
        data,
        snapshot,
        requests=requests,
        limits=limits,
        builder=build_word_snapshot,
        validator=validate,
    )


def map_word_span(data, snapshot, *, fragment_id, start, end, quote, limits=None):
    return map_word_spans(
        data,
        snapshot,
        requests=(VisibleSpanRequest(fragment_id, start, end, quote),),
        limits=limits,
    )[0]
