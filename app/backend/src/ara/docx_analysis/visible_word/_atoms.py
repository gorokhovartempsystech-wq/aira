"""Closed font glyph mapping and literal equations, without evaluating math."""

import re

from ara.docx_analysis.visible_main._reader import XML_SPACE, Run, check


def symbol(reader, node):
    reader.leaf(node)
    reader.attrs(node, {"font", "char"}, {"font", "char"})
    code = reader.attr(node, "char")
    check(re.fullmatch(r"[0-9A-Fa-f]{4}", code) is not None)
    # Microsoft Support: Wingdings 252 is the check mark. A glyph index is
    # font-dependent; unknown fonts/codes must never be cast to Unicode.
    check(reader.attr(node, "font") == "Wingdings" and int(code, 16) in (0xFC, 0xF0FC))
    return "\u2713"


def literal_math(reader, node, paragraph):
    ns = node.tag.rpartition("}")[0] + "}"
    check(not node.attrib)
    reader.container(node)
    for child in node:
        check(child.tag == ns + "r" and not child.attrib)
        reader.container(child)
        plan = Run(child)
        seen = set()
        text_started = False
        for item in child:
            if item.tag == ns + "rPr":
                check(not seen and not text_started and not item.attrib)
                seen.add("math_properties")
                reader.container(item)
                kinds = set()
                for prop in item:
                    check(prop.tag in (ns + "sty", ns + "nor") and prop.tag not in kinds)
                    kinds.add(prop.tag)
                    reader.leaf(prop)
                    check(set(prop.attrib) <= {ns + "val"})
                    value = prop.get(ns + "val")
                    check(
                        value in ("p", "i", "b", "bi")
                        if prop.tag == ns + "sty"
                        else value in (None, "0", "1", "false", "true", "off", "on")
                    )
            elif reader.name(item) == "rPr":
                check("word_properties" not in seen and not text_started)
                seen.add("word_properties")
                plan.selector, plan.properties = reader.properties(item, "rPr")
            else:
                check(item.tag == ns + "t")
                reader.leaf(item, text=True)
                check(set(item.attrib) <= {XML_SPACE})
                check(item.get(XML_SPACE) in (None, "preserve", "default"))
                text_started = True
                if item.text:
                    plan.atoms.append(("text", item, item.text))
        paragraph.runs.append(plan)
        # Field instructions/results must filter these runs just like ordinary text.
        reader.field_tokens.append(("run", reader.current_paragraph.node, plan))
    reader.event("metadata", "literal_math", node)
