"""Bound auxiliary XML and validate style/list references without external I/O."""

import io
import re
import zipfile

from .._xml import WORD_NAMESPACES, XmlValidator
from .._zip import chunks, parsing_end
from ..structure._xml import scan, word_name
from ._models import FormattingError

_TYPES = "application/vnd.openxmlformats-officedocument.wordprocessingml."
_RELS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/",
)


def attr(node, name):
    return node.attrs.get(node.name.rpartition("}")[0] + "}" + name)


def numeric(value):
    if (
        type(value) is not str
        or re.fullmatch(r"[0-9]{1,10}", value) is None
        or int(value) > 2147483647
    ):
        raise FormattingError("unsupported_format")
    return int(value)


class Part:
    def __init__(self, name, raw, bounds):
        count = 0

        def start(tag, attributes, depth):
            nonlocal count
            count += 1
            if count > bounds.max_aux_nodes or depth + 1 > bounds.max_aux_depth:
                raise FormattingError("format_limit_exceeded")

        XmlValidator(start).feed(raw, final=True)
        self.name, self.raw = name, raw
        self.nodes, self.codec, _ = scan(raw)
        self.root = self.nodes[()]
        self.namespace = self.root.name.rpartition("}")[0]
        self.child_map = {}
        for path, node in self.nodes.items():
            if path:
                self.child_map.setdefault(path[:-1], []).append(node)

    def children(self, node, name=None):
        return [
            n
            for n in self.child_map.get(node.path, ())
            if name is None or word_name(n.name) == name
        ]


def load_part(data, source, kind, limits, bounds):
    expected = _TYPES + kind + "+xml"
    types = {e.name: e.content_type for e in source.entries}
    candidates = {name for name, content in types.items() if content == expected}
    links = [
        link
        for link in source.relationships
        if link.source_part == source.main_part
        and link.relationship_type in tuple(r + kind for r in _RELS)
    ]
    if (
        len(candidates) != 1
        or len(links) != 1
        or links[0].target_mode != "Internal"
        or links[0].resolved_part not in candidates
    ):
        raise FormattingError("unsupported_format")
    name = candidates.pop()
    if types.get(name) != expected:
        raise FormattingError("unsupported_format")
    with (
        io.BytesIO(data[: parsing_end(data, limits)]) as buffer,
        zipfile.ZipFile(buffer) as archive,
    ):
        raw = b"".join(chunks(data, buffer, archive, archive.getinfo(name), limits.max_part_bytes))
    part = Part(name, raw, bounds)
    if part.namespace not in WORD_NAMESPACES or word_name(part.root.name) != kind:
        raise FormattingError("unsupported_format")
    return part


def check_style(part, identity):
    selected = [n for n in part.children(part.root, "style") if attr(n, "styleId") == identity]
    if len(selected) != 1 or attr(selected[0], "type") != "paragraph":
        raise FormattingError("unsupported_format")


def one(part, parent, name):
    values = part.children(parent, name)
    if len(values) != 1:
        raise FormattingError("unsupported_format")
    return values[0]


def check_list(part, identity, kind):
    selected = [
        n for n in part.children(part.root, "num") if numeric(attr(n, "numId")) == int(identity)
    ]
    if len(selected) != 1:
        raise FormattingError("unsupported_format")
    abstract = numeric(attr(one(part, selected[0], "abstractNumId"), "val"))
    defs = [
        n
        for n in part.children(part.root, "abstractNum")
        if numeric(attr(n, "abstractNumId")) == abstract
    ]
    if len(defs) != 1:
        raise FormattingError("unsupported_format")
    # A linked numbering style can redirect to a different abstract definition.
    # Resolving that style inheritance is outside this level-0 command contract.
    if part.children(defs[0], "numStyleLink"):
        raise FormattingError("unsupported_format")
    levels = [n for n in part.children(defs[0], "lvl") if attr(n, "ilvl") == "0"]
    overrides = [n for n in part.children(selected[0], "lvlOverride") if attr(n, "ilvl") == "0"]
    if len(levels) != 1 or len(overrides) > 1:
        raise FormattingError("unsupported_format")
    level = levels[0]
    if overrides:
        replacement = part.children(overrides[0], "lvl")
        if len(replacement) > 1:
            raise FormattingError("unsupported_format")
        if replacement:
            if attr(replacement[0], "ilvl") != "0":
                raise FormattingError("unsupported_format")
            level = replacement[0]
    if attr(one(part, level, "numFmt"), "val") != ("bullet" if kind == "bullet" else "decimal"):
        raise FormattingError("unsupported_format")


def next_ids(part):
    result = []
    for kind, key in (("abstractNum", "abstractNumId"), ("num", "numId")):
        values = [numeric(attr(n, key)) for n in part.children(part.root, kind)]
        if len(values) != len(set(values)) or (values and max(values) == 2147483647):
            raise FormattingError("unsupported_format")
        result.append(max(values, default=-1 if kind == "abstractNum" else 0) + 1)
    return result
