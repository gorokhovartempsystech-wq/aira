"""Prepare empty-paragraph style policy without publishing intermediate edits."""

from ..boundaries import BoundaryError, BoundaryLimits, SplitParagraph, export_boundary
from ..boundaries._guard import paragraph, validate_lists
from ..boundaries._tree import Tree, bounded_join, escape
from ..formatting import FormatLimits, FormattingError
from ..formatting._parts import attr, check_style, load_part
from ..projection import project_docx
from ..structure import StructureError
from ..structure._package import read_main, repack
from ..structure._xml import check_target
from ._models import EditorError


def unsupported():
    raise EditorError("unsupported_intent")


class Styles:
    def __init__(self, data, source, limits, namespace):
        self.part = load_part(data, source, "styles", limits, FormatLimits())
        if self.part.namespace != namespace:
            unsupported()
        defaults = [
            n
            for n in self.children(self.part.root, "style")
            if attr(n, "type") == "paragraph" and attr(n, "default") in ("1", "true", "on")
        ]
        if len(defaults) > 1:
            unsupported()
        self.default = attr(defaults[0], "styleId") if defaults else None
        if defaults and not self.default:
            unsupported()
        parents = [self.part.root]
        for name in ("docDefaults", "pPrDefault", "pPr"):
            values = self.children(parents[0], name) if parents else []
            if len(values) > 1:
                unsupported()
            parents = values
        self.default_number = self.number(parents[0]) if parents else None

    def children(self, node, name):
        found = self.part.children(node, name)
        if any(n.name != self.part.namespace + "}" + name for n in found):
            unsupported()
        return found

    def lookup(self, identity):
        check_style(self.part, identity)
        return next(
            n for n in self.children(self.part.root, "style") if attr(n, "styleId") == identity
        )

    def number(self, props):
        values = self.children(props, "numPr")
        if len(values) > 1:
            unsupported()
        if not values:
            return None
        ids = self.children(values[0], "numId")
        if len(ids) != 1:
            unsupported()
        value = attr(ids[0], "val")
        if (
            value is None
            or not 1 <= len(value) <= 10
            or not value.isascii()
            or not value.isdecimal()
            or int(value) > 2147483647
        ):
            unsupported()
        return int(value)

    def has_list(self, identity):
        seen, number = set(), None
        while identity is not None:
            if identity in seen or len(seen) >= 128:
                unsupported()
            seen.add(identity)
            style = self.lookup(identity)
            props = self.children(style, "pPr")
            if len(props) > 1:
                unsupported()
            if props:
                value = self.number(props[0])
                if number is None:
                    number = value
            bases = self.children(style, "basedOn")
            if len(bases) > 1:
                unsupported()
            identity = attr(bases[0], "val") if bases else None
            if bases and not identity:
                unsupported()
        return bool(number if number is not None else self.default_number)

    def next_style(self, current, exiting):
        style = self.lookup(current) if current is not None else None
        values = self.children(style, "next") if style is not None else []
        if len(values) > 1:
            unsupported()
        if values:
            target = attr(values[0], "val")
            if not target:
                unsupported()
            self.lookup(target)
        elif exiting:
            target = self.default
        else:
            return False, None
        if self.has_list(target):
            unsupported()
        return exiting or target != current, target


def _reset_empty(data, view, index, style, core):
    p = view.blocks[index]
    if p.kind != "paragraph" or p.text:
        unsupported()
    raw = read_main(data, view.source, core._limits)
    try:
        tree = Tree(raw, (p,), BoundaryLimits())
        node = tree.nodes[p.anchor.path]
        if tree.blocked:
            raise BoundaryError("unsupported_boundary")
        check_target(node, tree.nodes, p)
        paragraph(tree, node, p)
        validate_lists(tree, data, view.source, core._limits)
        namespace = node.name.rpartition("}")[0]
        props = (
            f'<aira:pPr xmlns:aira="{namespace}">'
            f'<aira:pStyle aira:val="{escape(style)}"/></aira:pPr>'
            if style is not None
            else ""
        ).encode(tree.codec)
        maximum = min(core._limits.max_xml_bytes, core._limits.max_part_bytes)
        main = bounded_join((raw[: node.start], tree.wrap(node, props), raw[node.end :]), maximum)
        result = repack(data, view.source, main, core._limits)
    except StructureError:
        raise BoundaryError("unsupported_boundary") from None
    actual = project_docx(result, limits=core._limits, projection_limits=core._projection_limits)
    if (
        actual.blocks[index].text
        or actual.blocks[index].style_id != style
        or actual.blocks[index].numbering_id is not None
    ):
        unsupported()
    before = [(b.kind, b.text if b.kind == "paragraph" else None) for b in view.blocks]
    after = [(b.kind, b.text if b.kind == "paragraph" else None) for b in actual.blocks]
    if before != after:
        unsupported()
    return result


def prepare_enter(core, before, index, offset):
    p = before.projection.blocks[index]

    def divide():
        return export_boundary(
            before.data,
            SplitParagraph(p.anchor, p.text, offset),
            limits=core._limits,
            projection_limits=core._projection_limits,
        )

    # Existing content is never restyled by a middle/start split. A direct
    # nonempty list continues independently of its style's next reference.
    if offset < len(p.text) or (p.text and p.numbering_id is not None):
        return divide(), index + 1
    try:
        raw = read_main(before.data, before.projection.source, core._limits)
        # Main root namespace is already known by the lexical source scanner.
        from ..structure._xml import scan

        nodes, _, _ = scan(raw)
        word_namespace = nodes[p.anchor.path].name.rpartition("}")[0]
        del nodes, raw
        styles = Styles(before.data, before.projection.source, core._limits, word_namespace)
        current = p.style_id if p.style_id is not None else styles.default
        if styles.has_list(current):
            unsupported()
        exiting = not p.text and p.numbering_id is not None
        if not p.text and not exiting:
            return divide(), index + 1
        change, target = styles.next_style(current, exiting)
        if exiting:
            return _reset_empty(before.data, before.projection, index, target, core), index
        data = divide()
        if change:
            view = project_docx(
                data, limits=core._limits, projection_limits=core._projection_limits
            )
            data = _reset_empty(data, view, index + 1, target, core)
        return data, index + 1
    except FormattingError:
        raise EditorError("unsupported_intent") from None
