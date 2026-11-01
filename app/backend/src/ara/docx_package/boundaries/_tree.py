"""Lexical nodes with bounded target contexts and namespace-aware rehoming."""

from xml.parsers import expat

from .. import DocxError
from ..editing._lexical import _opening
from ..structure._xml import scan
from ._guard import XML, unsupported
from ._models import BoundaryError


def escape(value):
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def bounded_join(chunks, maximum):
    pieces, total = [], 0
    for piece in chunks:
        total += len(piece)
        if total > maximum:
            raise DocxError("package_limit_exceeded")
        pieces.append(piece)
    return b"".join(pieces)


class Tree:
    def __init__(self, raw, paragraphs, bounds):
        self.raw = raw
        self.nodes, self.codec, self.blocked = scan(raw)
        self.child_map, self.text, self.list_ids = {}, {}, set()
        selected = {p.anchor.path for p in paragraphs}
        touched = 0
        for path, node in self.nodes.items():
            if path:
                self.child_map.setdefault(path[:-1], []).append(node)
            if any(path[: len(target)] == target for target in selected):
                touched += 1
                if touched > bounds.max_touched_nodes:
                    raise BoundaryError("boundary_limit_exceeded")
        for p in paragraphs:
            self.text.update({span.anchor.path: span.text for span in p.spans})
        self.contexts, self.declarations = {}, {}
        parser = expat.ParserCreate(namespace_separator="}")
        stack, pending = [], {}

        def ns(prefix, uri):
            pending[prefix or ""] = uri or ""

        def start(name, attrs):
            path = ()
            if stack:
                parent, context, count = stack[-1]
                path = parent + (count,)
                stack[-1] = parent, context, count + 1
                context = context | pending if pending else context
            else:
                context = {"": ""} | pending
            if path in selected:
                self.contexts[path] = context.copy()
            if path in selected or path[:-1] in selected:
                self.declarations[path] = set(pending)
            stack.append((path, context, 0))
            pending.clear()

        parser.StartNamespaceDeclHandler = ns
        parser.StartElementHandler = start
        parser.EndElementHandler = lambda name: stack.pop()
        parser.Parse(raw, True)

    def children(self, node):
        return self.child_map.get(node.path, ())

    def bytes(self, node):
        return self.raw[node.start : node.end]

    def whitespace(self, node):
        at = node.opening_end
        if node.empty:
            return
        for child in self.children(node):
            if self.raw[at : child.start].decode(self.codec).strip():
                unsupported()
            at = child.end
        if self.raw[at : node.close_start].decode(self.codec).strip():
            unsupported()

    def signature(self, node):
        if node is None:
            return ()
        children = self.children(node)
        return (
            node.name,
            tuple(sorted(node.attrs.items())),
            tuple(self.signature(n) for n in children),
        )

    def qualified(self, node):
        opening = self.raw[node.start : node.opening_end].decode(self.codec)
        return opening[1:].split()[0].rstrip("/>")

    def wrap(self, node, content):
        opening = self.raw[node.start : node.opening_end]
        if node.empty:
            opening = opening[: -len("/>".encode(self.codec))] + ">".encode(self.codec)
            closing = f"</{self.qualified(node)}>".encode(self.codec)
        else:
            closing = self.raw[node.close_start : node.end]
        return opening + content + closing

    def bindings(self, context, excluded=()):
        return "".join(
            f' xmlns{":" + prefix if prefix else ""}="{escape(uri)}"'
            for prefix, uri in sorted(context.items())
            if prefix not in excluded and prefix != "xml"
        )

    def new_paragraph(self, node, content):
        name = self.qualified(node)
        return (
            f"<{name}{self.bindings(self.contexts[node.path])}>".encode(self.codec)
            + content
            + f"</{name}>".encode(self.codec)
        )

    def rehome(self, run, parent, destination):
        raw = self.bytes(run)
        end = run.opening_end - run.start
        size = len(("/>" if run.empty else ">").encode(self.codec))
        context = {
            key: value
            for key, value in self.contexts[parent.path].items()
            if self.contexts[destination.path].get(key) != value
        }
        extra = self.bindings(context, self.declarations[run.path]).encode(self.codec)
        return raw[: end - size] + extra + raw[end - size :]

    def cut_text(self, node, text):
        opening = self.raw[node.start : node.opening_end].decode(self.codec)
        opening, name, _ = _opening(opening, node.attrs.get(XML + "}space"))
        return (opening + escape(text) + f"</{name}>").encode(self.codec)
