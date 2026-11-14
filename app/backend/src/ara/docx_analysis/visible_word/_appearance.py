"""Inert font/web/theme descriptions and one closed Office theme-family extension."""

import re

from ara.docx_analysis.visibility._grammar import boolean, check
from ara.docx_package._xml import WORD_NAMESPACES

DRAWING = {
    "http://schemas.openxmlformats.org/drawingml/2006/main",
    "http://purl.oclc.org/ooxml/drawingml/main",
}
# Closed presentation-only vocabulary; this is not a full DrawingML renderer/validator.
THEME_NAMES = frozenset(
    """
theme themeElements clrScheme dk1 lt1 dk2 lt2 accent1 accent2 accent3 accent4 accent5 accent6
hlink folHlink sysClr srgbClr schemeClr prstClr scrgbClr hslClr tint shade alpha alphaOff
alphaMod hue hueOff hueMod sat satOff satMod lum lumOff lumMod red redOff redMod green
greenOff greenMod blue blueOff blueMod gamma invGamma comp inv gray fontScheme majorFont
minorFont latin ea cs font fmtScheme fillStyleLst lnStyleLst effectStyleLst bgFillStyleLst
solidFill gradFill noFill pattFill fgClr bgClr gsLst gs lin path fillToRect tileRect ln
prstDash custDash ds round bevel miter headEnd tailEnd effectStyle effectLst outerShdw
innerShdw glow softEdge reflection blur fillOverlay scene3d camera lightRig rot backdrop
anchor norm up sp3d bevelT bevelB extrusionClr contourClr objectDefaults spDef lnDef txDef
spPr bodyPr lstStyle style lnRef fillRef effectRef fontRef extraClrSchemeLst extraClrScheme
clrMap
""".split()
)


THEME_ATTRIBUTES = {
    "theme": "name",
    "clrScheme": "name",
    "fontScheme": "name",
    "fmtScheme": "name",
    "sysClr": "val lastClr",
    "srgbClr": "val",
    "schemeClr": "val",
    "prstClr": "val",
    "scrgbClr": "r g b",
    "hslClr": "hue sat lum",
    "latin": "typeface panose pitchFamily charset",
    "ea": "typeface panose pitchFamily charset",
    "cs": "typeface panose pitchFamily charset",
    "font": "script typeface",
    "gradFill": "rotWithShape flip",
    "gs": "pos",
    "lin": "ang scaled",
    "path": "path",
    "fillToRect": "l t r b",
    "tileRect": "l t r b",
    "ln": "w cap cmpd algn",
    "prstDash": "val",
    "ds": "d sp",
    "miter": "lim",
    "pattFill": "prst",
    "headEnd": "type w len",
    "tailEnd": "type w len",
    "outerShdw": "blurRad dist dir sx sy kx ky algn rotWithShape",
    "innerShdw": "blurRad dist dir",
    "glow": "rad",
    "softEdge": "rad",
    "reflection": "blurRad stA stPos endA endPos dist dir fadeDir sx sy kx ky algn rotWithShape",
    "blur": "rad grow",
    "fillOverlay": "blend",
    "camera": "prst fov zoom",
    "rot": "lat lon rev",
    "lightRig": "rig dir",
    "anchor": "x y z",
    "norm": "dx dy dz",
    "up": "dx dy dz",
    "sp3d": "z extrusionH contourW prstMaterial",
    "bevelT": "w h prst",
    "bevelB": "w h prst",
    "lnRef": "idx",
    "fillRef": "idx",
    "effectRef": "idx",
    "fontRef": "idx",
    "clrMap": "bg1 tx1 bg2 tx2 accent1 accent2 accent3 accent4 accent5 accent6 hlink folHlink",
}
for _name in (
    "tint shade alpha alphaOff alphaMod hue hueOff hueMod sat satOff satMod lum "
    "lumOff lumMod red redOff redMod green greenOff greenMod blue blueOff blueMod"
).split():
    THEME_ATTRIBUTES[_name] = "val"
THEME_ATTRIBUTES = {name: frozenset(value.split()) for name, value in THEME_ATTRIBUTES.items()}


def empty_text(node):
    check(not (node.text or "").strip(" \t\r\n") and not (node.tail or "").strip(" \t\r\n"))


def fonts(root, *, embedding=None):
    ns = root.tag.rpartition("}")[0] + "}"
    check(root.tag in {"{" + n + "}fonts" for n in WORD_NAMESPACES} and not root.attrib)
    empty_text(root)
    names = set()
    allowed = {"altName", "panose1", "charset", "family", "notTrueType", "pitch", "sig"}
    for font in root:
        empty_text(font)
        check(font.tag == ns + "font" and set(font.attrib) == {ns + "name"})
        name = font.get(ns + "name")
        check(bool(name) and name not in names)
        names.add(name)
        seen = set()
        for node in font:
            empty_text(node)
            local = node.tag[len(ns) :] if node.tag.startswith(ns) else ""
            check(local not in seen and not len(node))
            seen.add(local)
            if local in {"embedRegular", "embedBold", "embedItalic", "embedBoldItalic"}:
                check(embedding is not None)
                embedding(node, ns)
                continue
            check(local in allowed)
            if local == "sig":
                check(
                    set(node.attrib)
                    <= {ns + n for n in ("usb0", "usb1", "usb2", "usb3", "csb0", "csb1")}
                )
            else:
                check(set(node.attrib) <= {ns + "val"})
                if local == "notTrueType":
                    boolean(node.get(ns + "val"))
                else:
                    check(node.get(ns + "val") is not None)


def web(root):
    ns = root.tag.rpartition("}")[0] + "}"
    check(root.tag in {"{" + n + "}webSettings" for n in WORD_NAMESPACES} and not root.attrib)
    empty_text(root)
    seen = set()
    for node in root:
        empty_text(node)
        check(
            node.tag in {ns + "allowPNG", ns + "doNotSaveAsSingleFile", ns + "optimizeForBrowser"}
            and node.tag not in seen
            and not len(node)
            and set(node.attrib) <= {ns + "val"}
        )
        seen.add(node.tag)
        boolean(node.get(ns + "val"))


def theme_family(node, ns):
    empty_text(node)
    check(not node.attrib and len(node) == 1)
    ext = node[0]
    empty_text(ext)
    check(ext.tag == ns + "ext" and ext.attrib == {"uri": "{05A4C25C-085E-4340-85A3-A5531E510DB2}"})
    check(len(ext) == 1)
    family = ext[0]
    empty_text(family)
    check(family.tag == "{http://schemas.microsoft.com/office/thememl/2012/main}themeFamily")
    check(not len(family) and set(family.attrib) == {"name", "id", "vid"})
    check(bool(family.get("name")))
    for key in ("id", "vid"):
        check(
            re.fullmatch(
                r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}", family.get(key)
            )
            is not None
        )


def theme(root):
    ns = root.tag.rpartition("}")[0] + "}"
    check(root.tag in {"{" + n + "}theme" for n in DRAWING})
    check(set(root.attrib) <= {"name"})
    tags = [n.tag for n in root]
    check(tags.count(ns + "themeElements") == 1 and len(tags) == len(set(tags)))
    check(
        set(tags)
        <= {ns + "themeElements", ns + "objectDefaults", ns + "extraClrSchemeLst", ns + "extLst"}
    )
    elements = next(n for n in root if n.tag == ns + "themeElements")
    check([n.tag for n in elements] == [ns + n for n in ("clrScheme", "fontScheme", "fmtScheme")])
    tags = {ns + n for n in THEME_NAMES}
    stack = [root]
    while stack:
        node = stack.pop()
        empty_text(node)
        if node.tag == ns + "extLst" and node in list(root):
            theme_family(node, ns)
            continue
        check(node.tag in tags)
        check(set(node.attrib) <= THEME_ATTRIBUTES.get(node.tag[len(ns) :], frozenset()))
        stack.extend(node)
