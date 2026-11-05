"""Text insertion and empty-run typing state with original run formatting."""

from ..boundaries import BoundaryError, BoundaryLimits, _divide
from ..boundaries._guard import local, paragraph, validate_lists
from ..boundaries._tree import Tree, bounded_join, escape
from ..projection import project_docx
from ..structure import StructureError
from ..structure._models import text_valid
from ..structure._package import read_main, repack
from ..structure._xml import check_target
from ._models import EditorError


def validate_text(text):
    if type(text) is not str:
        raise EditorError("invalid_input")
    if len(text) > 100000:
        raise EditorError("text_limit_exceeded")
    if not text_valid(text) or any(c in text for c in "\t\r\n"):
        raise EditorError("invalid_input")


def _prepare(core, snapshot, index):
    p = snapshot.projection.blocks[index]
    raw = read_main(snapshot.data, snapshot.projection.source, core._limits)
    try:
        tree = Tree(raw, (p,), BoundaryLimits())
        node = tree.nodes[p.anchor.path]
        if tree.blocked:
            raise BoundaryError("unsupported_boundary")
        check_target(node, tree.nodes, p)
        props, runs = paragraph(tree, node, p)
        validate_lists(tree, snapshot.data, snapshot.projection.source, core._limits)
    except StructureError:
        raise BoundaryError("unsupported_boundary") from None
    return tree, node, props, runs


def _template(tree, p, node, props, runs, offset, affinity, maximum):
    inside = next((s for s in p.spans if s.start < offset < s.end), None)
    prior = [s for s in p.spans if s.end <= offset and s.end > s.start]
    following = [s for s in p.spans if s.start >= offset]
    if inside is not None:
        chosen = inside
    elif affinity == "left":
        chosen = prior[-1] if prior else following[0] if following else None
    else:
        chosen = following[0] if following else prior[-1] if prior else None
    run = (
        tree.nodes[chosen.run_anchor.path]
        if chosen is not None
        else (runs[-1] if runs and affinity == "left" else runs[0] if runs else None)
    )
    namespace = node.name.rpartition("}")[0]
    holder = run if run is not None else props
    rpr = (
        next((n for n in tree.children(holder) if local(n, namespace) == "rPr"), None)
        if holder
        else None
    )
    formatting = tree.bytes(rpr) if rpr is not None else b""
    if holder is None:
        opening = f'<aira:r xmlns:aira="{namespace}">'
        closing = "</aira:r>"
    else:
        original = tree.qualified(holder)
        name = original.rpartition(":")[0] + ":r" if ":" in original else "r"
        tag = tree.raw[holder.start : holder.opening_end].decode(tree.codec)
        tail = tag[1 + len(original) :]
        if holder.empty:
            tail = tail[:-2] + ">"
        opening = "<" + name + tail
        closing = f"</{name}>"
    opening, closing = opening.encode(tree.codec), closing.encode(tree.codec)
    codec = tree.codec

    def make(text, *, soft_break=False):
        def chunks():
            yield opening
            yield formatting
            if soft_break:
                yield f'<aira:br xmlns:aira="{namespace}"/>'.encode(codec)
            else:
                for index, piece in enumerate(text.split("\t")):
                    if index:
                        yield f'<aira:tab xmlns:aira="{namespace}"/>'.encode(codec)
                    yield (
                        f'<aira:t xmlns:aira="{namespace}" xml:space="preserve">'
                        + escape(piece)
                        + "</aira:t>"
                    ).encode(codec)
            yield closing

        return bounded_join(chunks(), maximum)

    return make


def _finish(core, snapshot, index, tree, node, content, expected):
    maximum = min(core._limits.max_xml_bytes, core._limits.max_part_bytes)
    main = bounded_join(
        (tree.raw[: node.start], tree.wrap(node, content), tree.raw[node.end :]), maximum
    )
    try:
        data = repack(snapshot.data, snapshot.projection.source, main, core._limits)
    except StructureError:
        raise BoundaryError("unsupported_boundary") from None
    actual = project_docx(data, limits=core._limits, projection_limits=core._projection_limits)
    shape = [
        (b.kind, b.text if b.kind == "paragraph" else None) for b in snapshot.projection.blocks
    ]
    shape[index] = ("paragraph", expected)
    if shape != [(b.kind, b.text if b.kind == "paragraph" else None) for b in actual.blocks]:
        raise BoundaryError("unsupported_boundary")
    return data


def insert_text(core, snapshot, index, offset, text, affinity):
    tree, node, props, runs = _prepare(core, snapshot, index)
    p = snapshot.projection.blocks[index]
    maximum = min(core._limits.max_xml_bytes, core._limits.max_part_bytes)
    template = _template(tree, p, node, props, runs, offset, affinity, maximum)
    namespace = node.name.rpartition("}")[0]
    left, right = _divide(tree, runs, offset, namespace)
    maximum = min(core._limits.max_xml_bytes, core._limits.max_part_bytes)
    content = bounded_join(
        (tree.bytes(props) if props else b"", left, template(text), right), maximum
    )
    return _finish(
        core, snapshot, index, tree, node, content, p.text[:offset] + text + p.text[offset:]
    )


def insert_soft_break(core, snapshot, index, lo, hi, affinity):
    tree, node, props, runs = _prepare(core, snapshot, index)
    p = snapshot.projection.blocks[index]
    maximum = min(core._limits.max_xml_bytes, core._limits.max_part_bytes)
    template = _template(tree, p, node, props, runs, lo, affinity, maximum)
    namespace = node.name.rpartition("}")[0]
    left, _ = _divide(tree, runs, lo, namespace)
    _, right = _divide(tree, runs, hi, namespace)
    content = bounded_join(
        (tree.bytes(props) if props else b"", left, template("", soft_break=True), right),
        maximum,
    )
    return _finish(core, snapshot, index, tree, node, content, p.text[:lo] + "\n" + p.text[hi:])


def seed_after_enter(core, before, data, index, offset, affinity, destination):
    after = project_docx(data, limits=core._limits, projection_limits=core._projection_limits)
    old, new = before.projection.blocks[index], after.blocks[destination]
    if new.text or (old.style_id, old.numbering_id, old.numbering_level) != (
        new.style_id,
        new.numbering_id,
        new.numbering_level,
    ):
        return data
    tree, node, props, runs = _prepare(core, before, index)
    maximum = min(core._limits.max_xml_bytes, core._limits.max_part_bytes)
    template = _template(tree, old, node, props, runs, offset, affinity, maximum)
    # The pure split copied the old paragraph's namespace scope to the new p.
    # Only an empty result with unchanged style/list identity receives this seed.
    from ..session import SessionSnapshot

    snapshot = SessionSnapshot(before.revision, data, after, True, 0, 0)
    target, target_node, target_props, _ = _prepare(core, snapshot, destination)
    maximum = min(core._limits.max_xml_bytes, core._limits.max_part_bytes)
    content = bounded_join(
        (target.bytes(target_props) if target_props else b"", template("")), maximum
    )
    return _finish(core, snapshot, destination, target, target_node, content, "")
