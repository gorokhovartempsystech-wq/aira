"""Bounded source paths and lexical byte ranges; no whole-tree serialization."""

from dataclasses import dataclass
from xml.parsers import expat

from .._xml import WORD_NAMESPACES
from ..editing._lexical import _codec, _tag_end
from ._models import StructureError

_BLOCKED = frozenset(
    (
        "bookmarkStart",
        "bookmarkEnd",
        "commentRangeStart",
        "commentRangeEnd",
        "permStart",
        "permEnd",
        "proofErr",
        "fldChar",
        "instrText",
        "ins",
        "del",
        "moveFrom",
        "moveTo",
    )
)


@dataclass(slots=True)
class Node:
    name: str
    attrs: dict
    path: tuple[int, ...]
    start: int
    opening_end: int
    close_start: int
    end: int
    empty: bool
    annotated: bool = False


def word_name(name):
    namespace, _, local = name.rpartition("}")
    return local if namespace in WORD_NAMESPACES else None


def scan(data):
    codec = _codec(data)
    parser = expat.ParserCreate(namespace_separator="}")
    stack, nodes = [], {}
    global_blocked = False

    def declaration(version, encoding, standalone):
        if encoding is not None and encoding.lower().replace("_", "-") not in (
            "utf-8",
            "utf8",
            "utf-16",
            "utf-16le",
            "utf-16be",
            "utf-16-le",
            "utf-16-be",
        ):
            raise StructureError("unsupported_structure")

    def start(name, attrs):
        nonlocal global_blocked
        path = ()
        if stack:
            parent, count = stack[-1]
            path = parent.path + (count,)
            stack[-1] = parent, count + 1
        begin = parser.CurrentByteIndex
        opening_end = _tag_end(data, begin, codec)
        empty = data[begin:opening_end].decode(codec).endswith("/>")
        node = Node(name, attrs, path, begin, opening_end, opening_end, opening_end, empty)
        nodes[path] = node
        stack.append((node, 0))
        local = word_name(name)
        if local and (
            local in _BLOCKED
            or local.endswith("PrChange")
            or (local.startswith("move") and "Range" in local)
        ):
            global_blocked = True

    def end(name):
        node, _ = stack.pop()
        if not node.empty:
            node.close_start = parser.CurrentByteIndex
            node.end = _tag_end(data, node.close_start, codec)

    def annotation(*args):
        for node, _ in stack:
            node.annotated = True

    parser.XmlDeclHandler = declaration
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CommentHandler = annotation
    parser.ProcessingInstructionHandler = annotation
    parser.Parse(data, True)
    return nodes, codec, global_blocked


def new_paragraph(text, namespace):
    # Own namespace scope makes insertion valid even when the old p declared
    # its WML prefix locally; none of the old namespace bindings are changed.
    result = [f'<aira:p xmlns:aira="{namespace}"><aira:r>']
    for index, line in enumerate(text.split("\n")):
        if index:
            result.append("<aira:br/>")
        for offset, piece in enumerate(line.split("\t")):
            if offset:
                result.append("<aira:tab/>")
            escaped = piece.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            result.append('<aira:t xml:space="preserve">' + escaped + "</aira:t>")
    return "".join(result) + "</aira:r></aira:p>"


def check_target(node, nodes, paragraph):
    if paragraph.has_opaque or any(span.hyperlink for span in paragraph.spans) or node.annotated:
        raise StructureError("unsupported_structure")
    for path, child in nodes.items():
        if path[: len(node.path)] != node.path:
            continue
        relative = path[len(node.path) :]
        local = word_name(child.name)
        if local == "sectPr":
            raise StructureError("unsupported_structure")
        # Properties remain untouched (or disappear with explicit deletion).
        # Only standard pPr/rPr subtrees may contain non-content properties.
        ancestors = [nodes[node.path + relative[:i]] for i in range(1, len(relative) + 1)]
        if any(word_name(a.name) in ("pPr", "rPr") for a in ancestors):
            continue
        if local not in ("p", "r", "t", "tab", "br", "cr"):
            raise StructureError("unsupported_structure")
