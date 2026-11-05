"""Word building-block metadata; only stored child text is read."""

from ara.docx_analysis.visible_main._reader import Refusal, boolean, check
from ara.docx_analysis.visible_plain_controls._grammar import Grammar as PlainGrammar


class Grammar(PlainGrammar):
    def properties(self, node):
        types = [n for n in node if self.r.name(n) in ("text", "richText", "docPartObj")]
        if len(types) > 1:
            raise Refusal("unsupported_control_properties")
        super().properties(node)

    def extended_property(self, node):
        if self.r.name(node) != "docPartObj":
            return super().extended_property(node)
        r = self.r
        r.attrs(node)
        r.container(node)
        seen = set()
        for child in node:
            name = r.name(child)
            check(
                name in ("docPartGallery", "docPartCategory", "docPartUnique") and name not in seen
            )
            seen.add(name)
            if name == "docPartUnique":
                r.attrs(child, {"val"})
                r.leaf(child)
                boolean(r.attr(child, "val"))
            else:
                self.string(child)
