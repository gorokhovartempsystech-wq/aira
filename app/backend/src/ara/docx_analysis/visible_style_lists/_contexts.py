"""Only current paragraph-style numId; no style ilvl or implicit default numbering."""

from ara.docx_analysis.compatibility_contexts._factories import contexts
from ara.docx_analysis.visibility._grammar import check
from ara.docx_analysis.visible_unlisted._contexts import PaginationGrammar
from ara.docx_analysis.visible_unlisted._grammar import integer

STYLE_PROFILE = "docx-visibility/mc-style-numbering-v1"
CONTEXT_PROFILE = "docx-compatibility/selected-style-numbering-contexts-v1"


class Grammar(PaginationGrammar):
    def property_names(self, kind):
        return super().property_names(kind) | ({"numPr"} if kind == "pPr" else set())

    def leaf(self, node):
        if self.name(node) != "numPr":
            return super().leaf(node)
        self.attrs(node)
        children = self.children(node, {"numId"})
        check(len(children) == 1)
        child = children[0]
        super().leaf(child)
        self.attrs(child, {"val"}, {"val"})
        integer(self.attr(child, "val"))

    def defaults(self, node):
        for child in node:
            if self.name(child) == "pPrDefault":
                for prop in child:
                    if self.name(prop) == "pPr":
                        check(not any(self.name(n) == "numPr" for n in prop))
        return super().defaults(node)


def style_contexts(data, source, view, limits, proof_limits):
    return contexts(
        data,
        source,
        view,
        limits,
        proof_limits,
        grammar_type=Grammar,
        style_profile=STYLE_PROFILE,
        context_profile=CONTEXT_PROFILE,
    )
