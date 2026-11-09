"""Closed, text-free Word layout; never rewrite the retained package."""

import re

BORDER_STYLES = frozenset(
    "nil none single thick double dotted dashed dotDash dotDotDash triple "
    "thinThickSmallGap thickThinSmallGap thinThickThinSmallGap thinThickMediumGap "
    "thickThinMediumGap thinThickThinMediumGap thinThickLargeGap thickThinLargeGap "
    "thinThickThinLargeGap wave doubleWave dashSmallGap dashDotStroked "
    "threeDEmboss threeDEngrave outset inset".split()
)
THEMES = frozenset(
    "dark1 light1 dark2 light2 accent1 accent2 accent3 accent4 accent5 accent6 "
    "hyperlink followedHyperlink none background1 text1 background2 text2".split()
)


def borders(reader, node, require):
    reader.attrs(node)
    reader.container(node)
    seen = set()
    for child in node:
        name = reader.name(child)
        require(name in {"top", "left", "bottom", "right", "between", "bar"} and name not in seen)
        seen.add(name)
        reader.leaf(child)
        reader.attrs(
            child,
            {
                "val",
                "sz",
                "space",
                "color",
                "themeColor",
                "themeTint",
                "themeShade",
                "shadow",
                "frame",
            },
            {"val"},
        )
        require(reader.attr(child, "val") in BORDER_STYLES)
        for key in ("sz", "space"):
            value = reader.attr(child, key)
            if value is not None:
                require(
                    re.fullmatch(r"[0-9]{1,10}", value) is not None and int(value) <= 2147483647
                )
        color = reader.attr(child, "color")
        require(color in (None, "auto") or re.fullmatch(r"[0-9A-Fa-f]{6}", color) is not None)
        theme = reader.attr(child, "themeColor")
        require(theme is None or theme in THEMES)
        for key in ("themeTint", "themeShade"):
            value = reader.attr(child, key)
            require(value is None or re.fullmatch(r"[0-9A-Fa-f]{2}", value) is not None)
        for key in ("shadow", "frame"):
            require(reader.attr(child, key) in (None, "true", "false", "on", "off", "0", "1"))


def positional_tab(reader, node):
    reader.leaf(node)
    reader.attrs(node, {"alignment", "relativeTo", "leader"}, {"alignment", "relativeTo", "leader"})
    from ara.docx_analysis.visible_main._reader import check

    check(reader.attr(node, "alignment") in ("left", "center", "right"))
    check(reader.attr(node, "relativeTo") in ("margin", "indent"))
    check(reader.attr(node, "leader") in ("none", "dot", "hyphen", "underscore", "middleDot"))
