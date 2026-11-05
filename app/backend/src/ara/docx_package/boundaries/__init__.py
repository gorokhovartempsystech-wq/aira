"""Lossless body paragraph boundaries, with compatible-format joins."""

from .. import DocxLimits
from ..editing._models import EditError
from ..projection import ProjectionLimits, project_docx
from ..structure import StructureError
from ..structure._package import read_main, repack
from ..structure._xml import check_target, word_name
from ._guard import local, paragraph, unsupported, validate_lists
from ._models import BoundaryError, BoundaryLimits, JoinParagraphs, SplitParagraph
from ._tree import Tree, bounded_join

__all__ = ["BoundaryError", "BoundaryLimits", "JoinParagraphs", "SplitParagraph", "export_boundary"]


def _divide(tree, runs, offset, namespace):
    left, right, at = [], [], 0
    for run in runs:
        prop, a, b = b"", [], []
        for atom in tree.children(run):
            kind = local(atom, namespace)
            if kind == "rPr":
                prop = tree.bytes(atom)
                continue
            text = tree.text[atom.path]
            length = len(text)
            if (length and at + length <= offset) or (not length and at < offset):
                a.append(tree.bytes(atom))
            elif at >= offset:
                b.append(tree.bytes(atom))
            else:
                # Only text spans can have an internal code-point cut.
                cut = offset - at
                a.append(tree.cut_text(atom, text[:cut]))
                b.append(tree.cut_text(atom, text[cut:]))
            at += length
        if a and b:
            left.append(tree.wrap(run, prop + b"".join(a)))
            right.append(tree.wrap(run, prop + b"".join(b)))
        elif a:
            left.append(tree.bytes(run))
        elif b:
            right.append(tree.bytes(run))
        else:
            # Empty runs (possibly carrying typing formatting) are zero-width.
            (left if at < offset else right).append(tree.bytes(run))
    return b"".join(left), b"".join(right)


def export_boundary(
    data: bytes,
    command: SplitParagraph | JoinParagraphs,
    *,
    limits: DocxLimits | None = None,
    projection_limits: ProjectionLimits | None = None,
    boundary_limits: BoundaryLimits | None = None,
) -> bytes:
    if type(command) not in (SplitParagraph, JoinParagraphs):
        raise BoundaryError("invalid_input")
    command.__post_init__()
    bounds = boundary_limits if boundary_limits is not None else BoundaryLimits()
    if type(bounds) is not BoundaryLimits:
        raise BoundaryError("invalid_input")
    bounds.__post_init__()
    view = project_docx(data, limits=limits, projection_limits=projection_limits)
    anchors = (
        (command.anchor,)
        if type(command) is SplitParagraph
        else (command.left_anchor, command.right_anchor)
    )
    expected = (
        (command.expected_text,)
        if type(command) is SplitParagraph
        else (command.expected_left_text, command.expected_right_text)
    )
    if any(a.source_sha256 != view.source.sha256 for a in anchors):
        raise BoundaryError("stale_source")
    known = {b.anchor.path: b for b in view.blocks if b.kind == "paragraph"}
    if any(a.part_name != view.source.main_part or a.path not in known for a in anchors):
        raise BoundaryError("invalid_anchor")
    targets = [known[a.path] for a in anchors]
    if type(command) is JoinParagraphs:
        a, b = anchors
        if a.path[:-1] != b.path[:-1] or a.path[-1] + 1 != b.path[-1]:
            raise BoundaryError("nonadjacent_paragraphs")
    elif command.offset > len(targets[0].text):
        raise BoundaryError("invalid_position")
    if any(p.text != text for p, text in zip(targets, expected)):
        raise BoundaryError("text_mismatch")
    package_limits = limits if limits is not None else DocxLimits()
    try:
        raw = read_main(data, view.source, package_limits)
        tree = Tree(raw, targets, bounds)
        if tree.blocked:
            unsupported()
        prepared = []
        for target in targets:
            node = tree.nodes[target.anchor.path]
            parent = tree.nodes.get(node.path[:-1])
            if parent is None or word_name(parent.name) != "body":
                raise BoundaryError("invalid_anchor")
            check_target(node, tree.nodes, target)
            prop, runs = paragraph(tree, node, target)
            prepared.append((node, prop, runs))
        validate_lists(tree, data, view.source, package_limits)
        first, props, runs = prepared[0]
        maximum = min(package_limits.max_xml_bytes, package_limits.max_part_bytes)

        def signature(prop):
            return tuple(tree.signature(n) for n in tree.children(prop)) if prop else ()

        index = list(view.blocks).index(targets[0])
        shape = [(b.kind, b.text if b.kind == "paragraph" else None) for b in view.blocks]
        if type(command) is SplitParagraph:
            a, b = _divide(tree, runs, command.offset, first.name.rpartition("}")[0])
            props_xml = tree.bytes(props) if props else b""
            payload = tree.wrap(first, props_xml + a) + tree.new_paragraph(first, props_xml + b)
            main = bounded_join((raw[: first.start], payload, raw[first.end :]), maximum)
            shape[index : index + 1] = [
                ("paragraph", targets[0].text[: command.offset]),
                ("paragraph", targets[0].text[command.offset :]),
            ]
        else:
            second, second_props, second_runs = prepared[1]
            if first.name != second.name:
                unsupported()
            if signature(props) != signature(second_props):
                raise BoundaryError("incompatible_paragraph_format")
            if raw[first.end : second.start].decode(tree.codec).strip():
                unsupported()
            left_content = raw[first.opening_end : first.close_start] if not first.empty else b""

            def content():
                yield left_content
                for run in second_runs:
                    yield tree.rehome(run, second, first)

            payload = tree.wrap(first, bounded_join(content(), maximum))
            main = bounded_join(
                (raw[: first.start], payload, raw[first.end : second.start], raw[second.end :]),
                maximum,
            )
            shape[index : index + 2] = [("paragraph", targets[0].text + targets[1].text)]
        result = repack(data, view.source, main, package_limits)
        actual = project_docx(result, limits=limits, projection_limits=projection_limits)
        if [(b.kind, b.text if b.kind == "paragraph" else None) for b in actual.blocks] != shape:
            unsupported()
        return result
    except (StructureError, EditError):
        raise BoundaryError("unsupported_boundary") from None
