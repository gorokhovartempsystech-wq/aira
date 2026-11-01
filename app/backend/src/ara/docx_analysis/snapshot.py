"""Pure main-body snapshot and exact source-span mapping."""

from dataclasses import replace
from hashlib import sha256
from uuid import UUID

from ara.docx_package import DocxError, DocxLimits
from ara.docx_package.projection import project_docx
from ara.docx_package.projection._models import OpaqueBlock, Paragraph, Table

from ._manifest import fragment_id, manifest_digest
from ._models import (
    PROFILE,
    AnalysisFragment,
    AnalysisSegment,
    AnalysisSnapshot,
    CoverageItem,
    MappedSpan,
    SnapshotError,
    SnapshotLimits,
    SourceSlice,
)
from ._validate import valid_identity, validate_snapshot


def build_snapshot(
    data: bytes,
    *,
    document_id: UUID,
    storage_revision: int,
    source_sha256: str,
    limits: SnapshotLimits | None = None,
) -> AnalysisSnapshot:
    """Project validated bytes without changing them or retaining the package."""
    if type(data) is not bytes or not valid_identity(document_id, storage_revision, source_sha256):
        raise SnapshotError("invalid_input")
    if limits is None:
        limits = SnapshotLimits()
    if type(limits) is not SnapshotLimits:
        raise SnapshotError("invalid_input")
    limits.__post_init__()
    if len(data) > DocxLimits().max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise SnapshotError("source_mismatch")
    projection = project_docx(data)
    fragments = []
    coverage = []
    characters = segments_count = 0

    def budget(count, maximum):
        if count > maximum:
            raise SnapshotError("snapshot_limit_exceeded")

    def cover(status, code, part_name, anchor, fid=None):
        budget(len(coverage) + 1, limits.max_coverage_items)
        coverage.append(CoverageItem(status, code, part_name, anchor, fid))

    def visit(blocks, ancestry):
        nonlocal characters, segments_count
        for block in blocks:
            if isinstance(block, Table):
                for row in block.rows:
                    for cell in row.cells:
                        visit(cell.blocks, ancestry + (block.anchor, row.anchor, cell.anchor))
            elif isinstance(block, OpaqueBlock):
                cover("blocked", "opaque_block", block.anchor.part_name, block.anchor)
            elif isinstance(block, Paragraph):
                if block.has_opaque or any(s.kind == "opaque" for s in block.spans):
                    cover("blocked", "opaque_paragraph", block.anchor.part_name, block.anchor)
                elif not block.text.strip():
                    cover("empty", "empty_paragraph", block.anchor.part_name, block.anchor)
                else:
                    budget(len(fragments) + 1, limits.max_fragments)
                    start = characters + (2 if fragments else 0)
                    budget(start + len(block.text), limits.max_text_characters)
                    count = sum(s.end > s.start for s in block.spans)
                    budget(segments_count + count, limits.max_segments)
                    fid = fragment_id(block.anchor)
                    cover("included", "paragraph", block.anchor.part_name, block.anchor, fid)
                    mapped = tuple(
                        AnalysisSegment(s.kind, s.anchor, s.run_anchor, s.start, s.end)
                        for s in block.spans
                        if s.end > s.start
                    )
                    fragments.append(
                        AnalysisFragment(
                            fid,
                            block.anchor,
                            ancestry,
                            block.text,
                            start,
                            start + len(block.text),
                            mapped,
                        )
                    )
                    characters = start + len(block.text)
                    segments_count += count

    visit(projection.blocks, (projection.body_anchor,))
    for notice in projection.notices:
        cover("blocked", "notice:" + notice.code, notice.part_name, notice.anchor)
    if projection.has_unprojected_content and not any(c.status == "blocked" for c in coverage):
        cover("blocked", "unprojected_content", projection.source.main_part, projection.body_anchor)
    text = "\n\n".join(f.text for f in fragments)
    complete = not projection.has_unprojected_content and not any(
        c.status == "blocked" for c in coverage
    )
    result = AnalysisSnapshot(
        document_id,
        storage_revision,
        source_sha256,
        PROFILE,
        projection.source.main_part,
        projection.body_anchor,
        tuple(fragments),
        text,
        tuple(coverage),
        projection.has_unprojected_content,
        complete,
        sha256(text.encode("utf-8")).hexdigest(),
        "",
    )
    return replace(result, snapshot_sha256=manifest_digest(result))


def map_span(
    snapshot: AnalysisSnapshot,
    *,
    fragment_id: str,
    start: int,
    end: int,
    quote: str,
) -> MappedSpan:
    """Map code-point offsets; never repair a quote or search for another occurrence."""
    validate_snapshot(snapshot)
    if type(fragment_id) is not str or type(quote) is not str:
        raise SnapshotError("invalid_span")
    fragment = next((f for f in snapshot.fragments if f.fragment_id == fragment_id), None)
    if fragment is None:
        raise SnapshotError("unknown_fragment")
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(fragment.text)
        or fragment.text[start:end] != quote
    ):
        raise SnapshotError("invalid_span")
    slices = []
    for segment in fragment.segments:
        left, right = max(start, segment.start), min(end, segment.end)
        if left < right:
            slices.append(
                SourceSlice(
                    segment.kind,
                    segment.anchor,
                    segment.run_anchor,
                    left - segment.start,
                    right - segment.start,
                )
            )
    return MappedSpan(fragment_id, fragment.paragraph_anchor, start, end, tuple(slices))
