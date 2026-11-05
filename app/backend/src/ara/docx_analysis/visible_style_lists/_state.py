"""Resolve inherited selections before field scanning; consume through the outline policy."""

from dataclasses import fields

from ara.docx_analysis.visible_lists import ListItem
from ara.docx_analysis.visible_lists._state import Selection
from ara.docx_analysis.visible_main._build import paragraph_style
from ara.docx_analysis.visible_main._models import budget
from ara.docx_analysis.visible_outline._state import State as OutlineState
from ara.docx_analysis.visible_unlisted._grammar import integer

from ._definitions import Definitions, require
from ._models import StyleListItem


class State(Definitions):
    def __init__(self, data, source, bounds, namespace, limits, prepared):
        super().__init__(data, source, bounds, namespace)
        self.limits, self.counters, self.items = limits, {}, []
        self.generated, self.used, self.chain_entries = 0, False, 0
        self.bindings, self.choices = {}, {}
        self.context = prepared.contexts.styles
        self.styles = {s.style_id: s for s in self.context.styles}
        self.style_nodes = next(
            (p.nodes for p in prepared.view.parts if p.part_name == self.context.styles_part), {}
        )

    def select(self, reader, node):
        return OutlineState.select(self, reader, node)

    def inherited(self, identity):
        chain, key = [], identity
        while key is not None:
            # The full selected style graph is already resolved. Recheck the exact
            # referenced kind/status before using its original current properties.
            paragraph_style(self.styles, key)
            style = self.styles[key]
            budget(len(chain) + 1, self.limits.styles.max_chain_depth)
            chain.append(style.anchor)
            node = self.style_nodes.get(style.anchor.path)
            require(node is not None, "unresolved_style_list_binding")
            ns = node.tag.rpartition("}")[0] + "}"
            props = next((n for n in node if n.tag == ns + "pPr"), None)
            numpr = (
                None if props is None else next((n for n in props if n.tag == ns + "numPr"), None)
            )
            if numpr is not None:
                # The fixed source grammar has proved this one-child integer shape.
                number = integer(numpr[0].get(ns + "val"))
                if number == 0:
                    return None
                definition, binding = self.bound_level(number, identity)
                return Selection(number, numpr.anchor, definition), tuple(chain), binding
            key = style.based_on
        return None

    def attach(self, reader, plans):
        for p in plans:
            paragraph = reader.anchors[p.node]
            if paragraph in reader.explicit_lists:
                continue
            identity = (
                reader.attr(p.selector, "val")
                if p.selector is not None
                else self.context.default_paragraph_style
            )
            if identity is None:
                continue
            if identity not in self.choices:
                self.choices[identity] = self.inherited(identity)
            chosen = self.choices[identity]
            if chosen is None:
                continue
            require(reader.kind == "main", "unsupported_list_story")
            selection, chain, binding = chosen
            self.chain_entries += len(chain)
            budget(self.chain_entries, self.limits.max_xml_nodes)
            self.bindings[paragraph] = (
                None if p.selector is None else reader.anchors[p.selector],
                chain,
                binding,
            )
            reader.direct_lists[paragraph] = selection
            self.used = True

    def append(self, paragraph, selection, fragment_ids):
        OutlineState.append(self, paragraph, selection, fragment_ids)
        item = self.items[-1]
        inherited = self.bindings.get(paragraph)
        selector, chain, binding = (None, (), None) if inherited is None else inherited
        self.items[-1] = StyleListItem(
            **{f.name: getattr(item, f.name) for f in fields(ListItem)},
            numbering_source="direct" if inherited is None else "style",
            style_reference_anchor=selector,
            style_chain=chain,
            level_style_anchor=binding,
        )
