"""Explicit tab stops affect layout, not the retained text sequence."""

import re

from ara.docx_analysis.visibility._grammar import check


def tabs(r, node, *, require=check):
    r.attrs(node)
    r.container(node)
    for child in node:
        require(r.name(child) == "tab")
        r.attrs(child, {"val", "pos", "leader"}, {"val", "pos"})
        r.leaf(child)
        require(
            r.attr(child, "val")
            in ("clear", "left", "start", "center", "right", "end", "decimal", "bar", "num")
        )
        require(
            r.attr(child, "leader")
            in (None, "none", "dot", "hyphen", "underscore", "heavy", "middleDot")
        )
        value = r.attr(child, "pos")
        require(
            re.fullmatch(r"[+-]?[0-9]{1,10}", value) is not None and -(2**31) <= int(value) < 2**31
        )
