"""Project validated decisions without mutating, renumbering or serializing source XML."""

from types import MappingProxyType

from ara.docx_analysis.compatibility._models import Refused
from ara.docx_analysis.compatibility._names import words
from ara.docx_analysis.sections._xml import build_tree
from ara.docx_package._xml import WORD_NAMESPACES
from ara.docx_package.projection import SourceAnchor

from ._models import ViewNode, ViewPart

TEXT_LEAVES = frozenset(
    "{" + ns + "}" + name
    for ns in WORD_NAMESPACES
    for name in ("t", "delText", "instrText", "delInstrText")
)


class Projector:
    def __init__(self, source_sha256, part):
        self.sha, self.part = source_sha256, part.part_name
        self.actions = {a.anchor.path: a for a in part.actions}
        self.nodes = {}

    def anchor(self, path):
        return SourceAnchor(self.sha, self.part, path)

    def boundary(self, node, path):
        values = (node.text, *(n.tail for n in node))
        if node.tag in TEXT_LEAVES or any(next(words(v or ""), None) is not None for v in values):
            raise Refused("unsupported_compatibility_text_boundary", self.anchor(path))

    def structural(self, path):
        action = self.actions.get(path)
        return action is not None and action.kind != "strip_attributes"

    def children(self, node, path):
        # Generator promotion avoids copying a full descendant list at every wrapper.
        for i, child in enumerate(node):
            yield from self.expand(child, path + (i,))

    def expand(self, node, path):
        action = self.actions.get(path)
        if action is not None:
            if action.kind == "ignore_element":
                return
            if action.kind == "unwrap_element":
                self.boundary(node, path)
                yield from self.children(node, path)
                return
            if action.kind == "alternate_content":
                if action.selected_anchor is not None:
                    selected_path = action.selected_anchor.path
                    selected = node[selected_path[-1]]
                    self.boundary(selected, selected_path)
                    yield from self.children(selected, selected_path)
                return
        if any(self.structural(path + (i,)) for i in range(len(node))):
            self.boundary(node, path)
        removed = frozenset(action.attribute_names) if action is not None else ()
        attrs = MappingProxyType({k: v for k, v in node.attrib.items() if k not in removed})
        result = ViewNode(
            self.anchor(path),
            node.tag,
            attrs,
            node.text,
            node.tail,
            tuple(self.children(node, path)),
        )
        self.nodes[path] = result
        yield result


def project_part(data, part, source_sha256, bounds):
    projector = Projector(source_sha256, part)
    if projector.structural(()):
        raise Refused("unsupported_compatibility_root", part.root_anchor)
    original = build_tree(data, part.part_name, bounds)
    (root,) = projector.expand(original, ())
    return ViewPart(part.part_name, root, MappingProxyType(projector.nodes))
