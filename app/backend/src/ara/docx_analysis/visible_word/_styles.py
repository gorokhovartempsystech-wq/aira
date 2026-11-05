"""Validated spacing leaf and conservative agreement of duplicated style definitions."""

from ara.docx_analysis.visibility._grammar import boolean, check
from ara.docx_analysis.visible_style_lists._contexts import Grammar as StyleGrammar
from ara.docx_package._xml import WORD_NAMESPACES


class Grammar(StyleGrammar):
    def property_names(self, kind):
        return super().property_names(kind) | ({"contextualSpacing"} if kind == "pPr" else set())

    def properties(self, node, kind):
        if kind == "pPr":
            for child in node:
                if self.name(child) == "contextualSpacing":
                    self.leaf(child)
                    self.attrs(child, {"val"})
                    boolean(self.attr(child, "val"))
        return super().properties(node, kind)


def shape(node):
    # Style nodes contain properties, not document text. Whitespace indentation is inert.
    check(not (node.text or "").strip(" \t\r\n") and not (node.tail or "").strip(" \t\r\n"))
    return node.tag, tuple(sorted(node.attrib.items())), tuple(shape(n) for n in node)


def definitions(root):
    ns = root.tag.rpartition("}")[0] + "}"
    check(root.tag in {"{" + n + "}styles" for n in WORD_NAMESPACES} and not root.attrib)
    check(not (root.text or "").strip(" \t\r\n"))
    styles, metadata = {}, {}
    for node in root:
        if node.tag == ns + "style":
            key = node.get(ns + "styleId")
            check(key is not None and key not in styles)
            styles[key] = node
        else:
            check(
                node.tag in {ns + "docDefaults", ns + "latentStyles"} and node.tag not in metadata
            )
            metadata[node.tag] = shape(node)
    return ns, styles, metadata


def agree(base, effects, view):
    ns, a, ma = definitions(base)
    other_ns, b, mb = definitions(effects)
    check(ns == other_ns and ma == mb and b.keys() <= a.keys())
    check(all(shape(a[key]) == shape(b[key]) for key in b))
    missing = a.keys() - b.keys()
    check(all(not boolean(a[key].get(ns + "default"), False) for key in missing))
    selectors = {
        "pStyle",
        "rStyle",
        "tblStyle",
        "basedOn",
        "next",
        "link",
        "numStyleLink",
        "styleLink",
    }
    for part in view.parts:
        if part.root is base or part.root is effects:
            continue
        for node in part.nodes.values():
            uri, _, local = node.tag.rpartition("}")
            if uri + "}" == ns and local in selectors:
                check(node.get(ns + "val") not in missing)
    selector_tags = {ns + n for n in selectors}
    for key in b:
        stack = [a[key]]
        while stack:
            node = stack.pop()
            if node.tag in selector_tags:
                check(node.get(ns + "val") not in missing)
            stack.extend(node)
