"""Pagination properties do not change literal text or inherited visibility."""

from ara.docx_analysis.compatibility_contexts._anchors import SourceGrammar
from ara.docx_analysis.compatibility_contexts._factories import contexts
from ara.docx_analysis.visibility._grammar import boolean, check

STYLE_PROFILE = "docx-visibility/mc-pagination-styles-v1"
CONTEXT_PROFILE = "docx-compatibility/selected-pagination-contexts-v1"


class PaginationGrammar(SourceGrammar):
    def property_names(self, kind):
        names = super().property_names(kind)
        return names | {"widowControl"} if kind == "pPr" else names

    def properties(self, node, kind):
        if kind == "pPr":
            for child in node:
                if self.name(child) == "widowControl":
                    check(not len(child) and not (child.text or "").strip(" \t\r\n"))
                    self.attrs(child, {"val"})
                    boolean(self.attr(child, "val"))
        return super().properties(node, kind)


def pagination_contexts(data, source, view, limits, proof_limits):
    return contexts(
        data,
        source,
        view,
        limits,
        proof_limits,
        grammar_type=PaginationGrammar,
        style_profile=STYLE_PROFILE,
        context_profile=CONTEXT_PROFILE,
    )
