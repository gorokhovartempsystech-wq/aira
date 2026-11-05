"""Fixed logical-grid table profile with one authoritative source rebuild per mapping batch."""

from uuid import UUID

from ara.docx_analysis.visible_main._build import _build_snapshot
from ara.docx_analysis.visible_main._map import _map_spans
from ara.docx_analysis.visible_main._models import (
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSnapshot,
    VisibleSpanRequest,
)
from ara.docx_analysis.visible_main._shape import _validate

from ._reader import prepare_reader

PROFILE = "docx-analysis/final-visible-grid-tables-v1"


def build_grid_table_snapshot(
    data: bytes,
    *,
    document_id: UUID,
    storage_revision: int,
    source_sha256: str,
    limits: VisibleLimits | None = None,
) -> VisibleSnapshot:
    return _build_snapshot(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        prepare_reader=prepare_reader,
        profile=PROFILE,
    )


def _validate_grid_tables(snapshot, limits):
    return _validate(snapshot, limits, profile=PROFILE)


def map_grid_table_spans(
    data: bytes,
    snapshot: VisibleSnapshot,
    *,
    requests: tuple[VisibleSpanRequest, ...],
    limits: VisibleLimits | None = None,
) -> tuple[VisibleMappedSpan, ...]:
    return _map_spans(
        data,
        snapshot,
        requests=requests,
        limits=limits,
        builder=build_grid_table_snapshot,
        validator=_validate_grid_tables,
    )


def map_grid_table_span(
    data: bytes,
    snapshot: VisibleSnapshot,
    *,
    fragment_id: str,
    start: int,
    end: int,
    quote: str,
    limits: VisibleLimits | None = None,
) -> VisibleMappedSpan:
    return map_grid_table_spans(
        data,
        snapshot,
        requests=(VisibleSpanRequest(fragment_id, start, end, quote),),
        limits=limits,
    )[0]
