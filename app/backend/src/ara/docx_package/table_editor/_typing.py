"""A bounded lexical splice inside one simple cell paragraph, preserving its parent."""

from ..boundaries import BoundaryError, BoundaryLimits, _divide
from ..boundaries._guard import paragraph, validate_lists
from ..boundaries._tree import Tree, bounded_join
from ..editor._typing import _template
from ..projection import project_docx
from ..structure import StructureError
from ..structure._package import read_main, repack
from ..structure._xml import check_target, word_name
from ._selection import paragraphs


def change(core, before, p, lo, hi, text, affinity, *, soft_break=False):
    raw = read_main(before.data, before.projection.source, core._limits)
    try:
        tree = Tree(raw, (p,), BoundaryLimits())
        node = tree.nodes[p.anchor.path]
        parent = tree.nodes.get(p.anchor.path[:-1])
        if tree.blocked or parent is None or word_name(parent.name) != "tc":
            raise BoundaryError("unsupported_boundary")
        check_target(node, tree.nodes, p)
        props, runs = paragraph(tree, node, p)
        validate_lists(tree, before.data, before.projection.source, core._limits)
        maximum = min(core._limits.max_xml_bytes, core._limits.max_part_bytes)
        template = _template(tree, p, node, props, runs, lo, affinity, maximum)
        namespace = node.name.rpartition("}")[0]
        left, _ = _divide(tree, runs, lo, namespace)
        _, right = _divide(tree, runs, hi, namespace)
        content = bounded_join(
            (
                tree.bytes(props) if props else b"",
                left,
                template(text, soft_break=soft_break),
                right,
            ),
            maximum,
        )
        main = bounded_join(
            (tree.raw[: node.start], tree.wrap(node, content), tree.raw[node.end :]), maximum
        )
        result = repack(before.data, before.projection.source, main, core._limits)
    except StructureError:
        raise BoundaryError("unsupported_boundary") from None
    actual = project_docx(result, limits=core._limits, projection_limits=core._projection_limits)
    expected = {x.anchor.path: x.text for x in paragraphs(before.projection)}
    expected[p.anchor.path] = p.text[:lo] + ("\n" if soft_break else text) + p.text[hi:]
    if expected != {x.anchor.path: x.text for x in paragraphs(actual)}:
        raise BoundaryError("unsupported_boundary")
    return result
