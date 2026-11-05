"""One bounded lexical paragraph splice for plain-text clipboard content."""

from ..boundaries import BoundaryError, _divide
from ..boundaries._tree import bounded_join
from ..projection import project_docx
from ..structure import StructureError
from ..structure._models import text_valid
from ..structure._package import repack
from ._models import EditorError, PasteLimits
from ._typing import _prepare, _template


def validate_paste(text, limits):
    if limits is None:
        limits = PasteLimits()
    if type(limits) is not PasteLimits or type(text) is not str:
        raise EditorError("invalid_input")
    limits.__post_init__()
    if len(text) > limits.max_text_chars:
        raise EditorError("text_limit_exceeded")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text_valid(normalized):
        raise EditorError("invalid_input")
    if normalized.count("\n") > limits.max_new_paragraphs:
        raise EditorError("text_limit_exceeded")
    return normalized


def prepare_paste(core, snapshot, index, lo, hi, text, affinity):
    tree, node, props, runs = _prepare(core, snapshot, index)
    paragraph = snapshot.projection.blocks[index]
    maximum = min(core._limits.max_xml_bytes, core._limits.max_part_bytes)
    namespace = node.name.rpartition("}")[0]
    template = _template(tree, paragraph, node, props, runs, lo, affinity, maximum)
    left, _ = _divide(tree, runs, lo, namespace)
    _, right = _divide(tree, runs, hi, namespace)
    properties = tree.bytes(props) if props else b""
    lines = text.split("\n")

    def pieces():
        yield tree.raw[: node.start]
        for position, line in enumerate(lines):
            content = bounded_join(
                (
                    properties,
                    left if position == 0 else b"",
                    template(line),
                    right if position == len(lines) - 1 else b"",
                ),
                maximum,
            )
            yield tree.wrap(node, content) if position == 0 else tree.new_paragraph(node, content)
        yield tree.raw[node.end :]

    main = bounded_join(pieces(), maximum)
    try:
        result = repack(snapshot.data, snapshot.projection.source, main, core._limits)
    except StructureError:
        raise BoundaryError("unsupported_boundary") from None
    actual = project_docx(result, limits=core._limits, projection_limits=core._projection_limits)
    expected = [
        (b.kind, b.text if b.kind == "paragraph" else None) for b in snapshot.projection.blocks
    ]
    values = list(lines)
    values[0] = paragraph.text[:lo] + values[0]
    values[-1] += paragraph.text[hi:]
    expected[index : index + 1] = [("paragraph", value) for value in values]
    if expected != [(b.kind, b.text if b.kind == "paragraph" else None) for b in actual.blocks]:
        raise BoundaryError("unsupported_boundary")
    return result, index + len(lines) - 1, len(lines[-1]) + (lo if len(lines) == 1 else 0)
