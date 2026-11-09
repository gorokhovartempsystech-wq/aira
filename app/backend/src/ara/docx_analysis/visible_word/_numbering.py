"""Selected numbering grammar keeps physical addresses under MC wrappers."""

from ara.docx_analysis.compatibility_contexts._anchors import SourceAnchors
from ara.docx_analysis.visibility._grammar import Unsupported, check
from ara.docx_analysis.visible_lists._state import Selection
from ara.docx_analysis.visible_main._build import paragraph_style
from ara.docx_analysis.visible_main._models import budget
from ara.docx_analysis.visible_style_lists._definitions import require
from ara.docx_analysis.visible_style_lists._grammar import Grammar as BaseGrammar
from ara.docx_analysis.visible_style_lists._state import State as StyleState
from ara.docx_analysis.visible_unlisted._grammar import integer
from ara.docx_analysis.visible_unlisted._numbering import RELATIONS, parts


class Grammar(SourceAnchors, BaseGrammar):
    pass


class State(StyleState):
    def inherited(self, identity):
        chain, key, selected_level = [], identity, None
        while key is not None:
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
                values = {n.tag[len(ns) :]: integer(n.get(ns + "val")) for n in numpr}
                if selected_level is None:
                    selected_level = values.get("ilvl")
                if "numId" not in values:
                    key = style.based_on
                    continue
                number = values["numId"]
                if number == 0:
                    return None
                definition, binding = self.bound_level(number, identity)
                # Require agreement: Word and ISO differ on conflicting style ilvl.
                require(
                    selected_level is None or selected_level == definition.level,
                    "ambiguous_style_list_level",
                )
                return Selection(number, numpr.anchor, definition), tuple(chain), binding
            key = style.based_on
        return None

    def __init__(self, data, source, bounds, namespace, limits, prepared):
        self.part, self.linked, self.failed, self.cache = None, False, False, {}
        self.abstracts, self.instances = {}, {}
        self.limits, self.counters, self.items = limits, {}, []
        self.generated, self.used, self.chain_entries = 0, False, 0
        self.bindings, self.choices = {}, {}
        self.context = prepared.contexts.styles
        self.styles = {s.style_id: s for s in self.context.styles}
        self.style_nodes = next(
            (p.nodes for p in prepared.view.parts if p.part_name == self.context.styles_part), {}
        )
        try:
            found = parts(source)
            links = [
                r
                for r in source.relationships
                if r.relationship_type in RELATIONS or r.resolved_part in found
            ]
            check(len(found) <= 1 and len(links) <= 1)
            expected = (
                "http://purl.oclc.org/ooxml/officeDocument/relationships/numbering"
                if "purl.oclc.org" in namespace
                else "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
            )
            check(
                all(
                    r.source_part == source.main_part
                    and r.relationship_type == expected
                    and r.target_mode == "Internal"
                    and r.resolved_part in found
                    for r in links
                )
            )
            check(not any(r.source_part in found for r in source.relationships))
            if not found:
                return
            part = next(iter(found))
            root = next(p.root for p in prepared.view.parts if p.part_name == part)
            check(root.tag == namespace + "numbering")
            grammar = Grammar(root, source.sha256, part)
            grammar.prove()
            self.part, self.g, self.linked = part, grammar, bool(links)
            for node in root:
                name = self.g.name(node)
                if name == "abstractNum":
                    self.abstracts[integer(self.g.attr(node, "abstractNumId"))] = node
                elif name == "num":
                    self.instances[integer(self.g.attr(node, "numId"))] = node
        except Unsupported:
            self.failed = True
