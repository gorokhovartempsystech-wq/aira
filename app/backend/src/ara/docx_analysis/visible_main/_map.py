"""One source-backed rebuild per batch, then exact interval-indexed mapping."""

from bisect import bisect_right

from ._build import build_visible_snapshot
from ._models import (
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSnapshot,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
    budget,
    checked_limits,
)
from ._shape import validate


def map_visible_spans(
    data: bytes,
    snapshot: VisibleSnapshot,
    *,
    requests: tuple[VisibleSpanRequest, ...],
    limits: VisibleLimits | None = None,
) -> tuple[VisibleMappedSpan, ...]:
    limits = checked_limits(limits)
    if type(data) is not bytes or type(requests) is not tuple:
        raise VisibleViewError("invalid_input")
    budget(len(requests), limits.max_span_requests)
    characters = 0
    for q in requests:
        if (
            type(q) is not VisibleSpanRequest
            or type(q.fragment_id) is not str
            or type(q.start) is not int
            or type(q.end) is not int
            or type(q.quote) is not str
        ):
            raise VisibleViewError("invalid_input")
        if not 0 <= q.start < q.end:
            raise VisibleViewError("invalid_span")
        if len(q.fragment_id) > 128:
            raise VisibleViewError("invalid_input")
        characters += len(q.quote)
        budget(characters, limits.max_requested_characters)
    validate(snapshot, limits)
    expected = build_visible_snapshot(
        data,
        document_id=snapshot.document_id,
        storage_revision=snapshot.storage_revision,
        source_sha256=snapshot.source_sha256,
        limits=limits,
    )
    if snapshot != expected:
        raise VisibleViewError("invalid_snapshot")
    index = {f.fragment_id: (f, tuple(p.end for p in f.pieces)) for f in expected.fragments}
    result, count = [], 0
    for q in requests:
        item = index.get(q.fragment_id)
        if item is None:
            raise VisibleViewError("unknown_fragment")
        f, ends = item
        if not q.end <= len(f.text) or f.text[q.start : q.end] != q.quote:
            raise VisibleViewError("invalid_span")
        slices = []
        i = bisect_right(ends, q.start)
        while i < len(f.pieces) and f.pieces[i].start < q.end:
            p = f.pieces[i]
            count += 1
            budget(count, limits.max_mapped_slices)
            slices.append(
                VisibleSourceSlice(
                    p.kind,
                    p.anchor,
                    p.run_anchor,
                    p.paragraph_anchor,
                    p.source_start + max(q.start, p.start) - p.start,
                    p.source_start + min(q.end, p.end) - p.start,
                )
            )
            i += 1
        result.append(VisibleMappedSpan(q.fragment_id, q.start, q.end, tuple(slices)))
    return tuple(result)


def map_visible_span(
    data: bytes,
    snapshot: VisibleSnapshot,
    *,
    fragment_id: str,
    start: int,
    end: int,
    quote: str,
    limits: VisibleLimits | None = None,
) -> VisibleMappedSpan:
    return map_visible_spans(
        data,
        snapshot,
        requests=(VisibleSpanRequest(fragment_id, start, end, quote),),
        limits=limits,
    )[0]
