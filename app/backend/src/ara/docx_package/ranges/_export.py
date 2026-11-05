"""Resolve a batch against one source, then delegate one whole-span export."""

from bisect import bisect_right
from dataclasses import dataclass

from .. import DocxLimits, editing
from .._xml import WORD_NAMESPACES
from ..projection import DocxProjection, ProjectionLimits, project_docx
from ..projection._models import Paragraph, Span
from ..projection._parse import parse_main
from ._models import RangeEdit, RangeError, RangeLimits


@dataclass(frozen=True, slots=True)
class _ResolvedRange:
    edit: RangeEdit
    paragraph: Paragraph
    first: int
    last: int
    start: int
    end: int


def _span_index(projection: DocxProjection) -> dict[tuple[int, ...], tuple[Paragraph, int]]:
    result = {}
    stack = list(projection.blocks)
    while stack:
        block = stack.pop()
        if block.kind == "paragraph":
            for index, span in enumerate(block.spans):
                if span.kind == "text":
                    result[span.anchor.path] = (block, index)
        elif block.kind == "table":
            stack.extend(child for row in block.rows for cell in row.cells for child in cell.blocks)
    return result


def _resolve(edit, projection, index) -> _ResolvedRange:
    for position in (edit.start, edit.end):
        anchor = position.anchor
        if anchor.source_sha256 != projection.source.sha256:
            raise RangeError("stale_source")
        if anchor.part_name != projection.source.main_part or anchor.path not in index:
            raise RangeError("invalid_anchor")
    paragraph, first = index[edit.start.anchor.path]
    end_paragraph, last = index[edit.end.anchor.path]
    if (
        paragraph is not end_paragraph
        or first > last
        or edit.start.offset > len(paragraph.spans[first].text)
        or edit.end.offset > len(end_paragraph.spans[last].text)
    ):
        raise RangeError("invalid_range")
    start = paragraph.spans[first].start + edit.start.offset
    end = paragraph.spans[last].start + edit.end.offset
    if start > end or (start == end and edit.start != edit.end):
        raise RangeError("invalid_range")
    if edit.expected_text != paragraph.text[start:end]:
        raise RangeError("text_mismatch")
    return _ResolvedRange(edit, paragraph, first, last, start, end)


def _check_conflicts(ranges: list[_ResolvedRange]) -> None:
    # Sorting by source coordinates also puts an insertion before a nonempty
    # range starting there. After each accepted neighbor, no older interval can
    # extend further, so neighboring comparisons suffice.
    previous = None
    for current in ranges:
        if previous is not None and previous.paragraph is current.paragraph:
            if previous.end > current.start or (
                previous.end == current.start
                and (previous.start == previous.end or current.start == current.end)
            ):
                raise RangeError("conflicting_edits")
        previous = current


def _check_spans(ranges: list[_ResolvedRange], limits: RangeLimits) -> None:
    touched = set()
    for item in ranges:
        if any(char in item.edit.replacement_text for char in "\t\r\n"):
            raise RangeError("unsupported_range")
        first_span = item.paragraph.spans[item.first]
        link = first_span.hyperlink.anchor if first_span.hyperlink is not None else None
        for index in range(item.first, item.last + 1):
            span = item.paragraph.spans[index]
            identity = span.hyperlink.anchor if span.hyperlink is not None else None
            if span.kind != "text" or identity != link:
                raise RangeError("unsupported_range")
            touched.add(span.anchor.path)
            if len(touched) > limits.max_touched_spans:
                raise RangeError("range_limit_exceeded")


def _check_bookmarks(data, projection, ranges, limits, projection_limits) -> None:
    root = parse_main(data, projection.source, limits, projection_limits)
    tags = {
        f"{{{namespace}}}{name}"
        for namespace in WORD_NAMESPACES
        for name in ("bookmarkStart", "bookmarkEnd")
    }
    markers = []
    stack = [(root, ())]
    while stack:
        node, path = stack.pop()
        if node.tag in tags:
            markers.append(path)
        stack.extend((child, path + (index,)) for index, child in enumerate(node))
    markers.sort()
    for item in ranges:
        following = bisect_right(markers, item.edit.start.anchor.path)
        if following < len(markers) and markers[following] < item.edit.end.anchor.path:
            raise RangeError("unsupported_range")


def _aggregate(ranges: list[_ResolvedRange]) -> tuple[editing.TextEdit, ...]:
    # Each local splice still uses original offsets. Empty deletion splices
    # have no effect, but their spans have already been guarded and budgeted.
    patches: dict[tuple[int, ...], list[tuple[int, int, str]]] = {}
    spans: dict[tuple[int, ...], Span] = {}
    for item in ranges:
        for index in range(item.first, item.last + 1):
            span = item.paragraph.spans[index]
            start = item.edit.start.offset if index == item.first else 0
            end = item.edit.end.offset if index == item.last else len(span.text)
            replacement = item.edit.replacement_text if index == item.first else ""
            if start != end or replacement:
                path = span.anchor.path
                spans[path] = span
                patches.setdefault(path, []).append((start, end, replacement))
    edits = []
    for path in sorted(patches):
        span = spans[path]
        pieces = []
        cursor = 0
        for start, end, replacement in sorted(patches[path]):
            pieces.extend((span.text[cursor:start], replacement))
            cursor = end
        pieces.append(span.text[cursor:])
        text = "".join(pieces)
        if text != span.text:
            edits.append(editing.TextEdit(span.anchor, span.text, text))
    return tuple(edits)


def export_docx_ranges(
    data: bytes,
    edits: tuple[RangeEdit, ...],
    *,
    limits: DocxLimits | None = None,
    projection_limits: ProjectionLimits | None = None,
    range_limits: RangeLimits | None = None,
) -> bytes:
    """Atomically replace in-paragraph source ranges without structural edits.

    All endpoints, expected text and conflicts are checked before any export.
    A no-op retains the exact input bytes and original run distribution. After
    actual changes, obtain a new projection before submitting further ranges.
    """
    projection = project_docx(data, limits=limits, projection_limits=projection_limits)
    if range_limits is None:
        range_limits = RangeLimits()
    if type(range_limits) is not RangeLimits or type(edits) is not tuple:
        raise RangeError("invalid_input")
    range_limits.__post_init__()
    if len(edits) > range_limits.max_edits:
        raise RangeError("range_limit_exceeded")
    total = 0
    for edit in edits:
        if type(edit) is not RangeEdit:
            raise RangeError("invalid_input")
        edit.__post_init__()
        total += len(edit.replacement_text)
    if total > range_limits.max_total_replacement_chars:
        raise RangeError("range_limit_exceeded")

    index = _span_index(projection)
    resolved = [_resolve(edit, projection, index) for edit in edits]
    resolved.sort(key=lambda item: (item.paragraph.anchor.path, item.start, item.end))
    _check_conflicts(resolved)
    changed = [item for item in resolved if item.edit.expected_text != item.edit.replacement_text]
    _check_spans(changed, range_limits)
    if changed:
        _check_bookmarks(
            data,
            projection,
            changed,
            limits if limits is not None else DocxLimits(),
            projection_limits if projection_limits is not None else ProjectionLimits(),
        )
    replacements = _aggregate(changed)
    edit_limits = editing.EditLimits(
        max_edits=max(1, len(replacements)),
        max_total_replacement_chars=max(
            1, sum(len(edit.replacement_text) for edit in replacements)
        ),
    )
    return editing.export_docx(
        data,
        replacements,
        limits=limits,
        projection_limits=projection_limits,
        edit_limits=edit_limits,
    )
