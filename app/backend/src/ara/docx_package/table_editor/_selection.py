"""Physical paragraphs in original traversal order; no flattened public projection."""

from ..editor import EditorError, EditorSelection


def paragraphs(projection):
    stack = list(reversed(projection.blocks))
    while stack:
        block = stack.pop()
        if block.kind == "paragraph":
            yield block
        elif block.kind == "table":
            children = [b for row in block.rows for cell in row.cells for b in cell.blocks]
            stack.extend(reversed(children))


def points(selection, document):
    if type(selection) is not EditorSelection:
        raise EditorError("invalid_input")
    selection.__post_init__()
    source = document.projection.source
    index = {p.anchor.path: p for p in paragraphs(document.projection)}
    result = []
    for caret in (selection.anchor, selection.focus):
        anchor = caret.anchor
        if anchor.source_sha256 != source.sha256:
            raise EditorError("stale_selection")
        p = index.get(anchor.path)
        if anchor.part_name != source.main_part or p is None or caret.offset > len(p.text):
            raise EditorError("invalid_selection")
        result.append((anchor.path, caret.offset, caret.affinity))
    return tuple(result)


def verify_metadata(data, *, saved_sha256, selection):
    # Independent original-package proof, not trust in a persisted anchor/hash.
    from ..projection import ProjectionLimits
    from ..session import DocxSession

    document = DocxSession.restore(
        data,
        saved_sha256=saved_sha256,
        projection_limits=ProjectionLimits(isolate_complex_fields=True),
    ).snapshot()
    points(selection, document)
