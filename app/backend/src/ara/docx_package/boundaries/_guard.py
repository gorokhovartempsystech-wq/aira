"""Conservative copyable-property shapes; no style inheritance rewriting."""

from ..formatting import FormatLimits, FormattingError
from ..formatting._parts import check_list, load_part
from ._models import BoundaryError

XML = "http://www.w3.org/XML/1998/namespace"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
_ON = set(
    "b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof "
    "snapToGrid vanish webHidden rtl cs specVanish".split()
)
_PARA_ON = set(
    "keepNext keepLines widowControl contextualSpacing bidi snapToGrid "
    "suppressAutoHyphens adjustRightInd".split()
)
_VAL = set(
    "pStyle numId ilvl outlineLvl jc rStyle w kern position sz szCs highlight vertAlign em".split()
)
_ATTRS = {
    "ind": set(
        "left leftChars right rightChars start startChars end endChars firstLine "
        "firstLineChars hanging hangingChars".split()
    ),
    "rFonts": set(
        "ascii hAnsi eastAsia cs hint asciiTheme hAnsiTheme eastAsiaTheme cstheme".split()
    ),
    "color": set("val themeColor themeTint themeShade".split()),
    "u": set("val color themeColor themeTint themeShade".split()),
    "lang": set("val eastAsia bidi".split()),
}
_RP = _ON | set(
    "rStyle rFonts color spacing w kern position sz szCs highlight u vertAlign em lang".split()
)
_PP = _PARA_ON | set("pStyle numPr spacing ind jc outlineLvl tabs rPr".split())


def unsupported():
    raise BoundaryError("unsupported_boundary")


def local(node, namespace):
    prefix = namespace + "}"
    if not node.name.startswith(prefix):
        unsupported()
    return node.name[len(prefix) :]


def attrs(node, namespace, allowed):
    if any(key not in {namespace + "}" + n for n in allowed} for key in node.attrs):
        unsupported()


def properties(tree, node, namespace, kind):
    attrs(node, namespace, set())
    allowed = (
        _PP
        if kind == "pPr"
        else _RP
        if kind == "rPr"
        else {"tab"}
        if kind == "tabs"
        else {"numId", "ilvl"}
    )
    seen = set()
    for child in tree.children(node):
        name = local(child, namespace)
        if name not in allowed or (kind != "tabs" and name in seen):
            unsupported()
        seen.add(name)
        if name in ("rPr", "tabs", "numPr"):
            properties(tree, child, namespace, name)
            continue
        if tree.children(child):
            unsupported()
        if name == "spacing":
            fields = (
                {
                    "before",
                    "beforeLines",
                    "beforeAutospacing",
                    "after",
                    "afterLines",
                    "afterAutospacing",
                    "line",
                    "lineRule",
                }
                if kind == "pPr"
                else {"val"}
            )
        elif kind == "tabs":
            fields = {"val", "pos", "leader"}
        else:
            fields = {"val"} if name in (_ON | _PARA_ON | _VAL) else _ATTRS[name]
        attrs(child, namespace, fields)
        tree.whitespace(child)
    tree.whitespace(node)
    if kind == "numPr":
        if "numId" not in seen:
            unsupported()
        values = {local(n, namespace): n.attrs.get(namespace + "}val") for n in tree.children(node)}
        if values.get("ilvl", "0") != "0":
            unsupported()
        tree.list_ids.add(values["numId"])


def paragraph(tree, node, paragraph):
    namespace = node.name.rpartition("}")[0]
    allowed = {namespace + "}" + k for k in ("rsidR", "rsidRDefault", "rsidP", "rsidRPr")}
    allowed |= {W14 + "}paraId", W14 + "}textId"}
    if set(node.attrs) - allowed:
        unsupported()
    children = tree.children(node)
    prop = None
    runs = []
    for index, child in enumerate(children):
        name = local(child, namespace)
        if name == "pPr" and index == 0:
            properties(tree, child, namespace, name)
            prop = child
        elif name == "r":
            attrs(child, namespace, {"rsidR", "rsidRPr", "rsidDel"})
            for i, atom in enumerate(tree.children(child)):
                atom_name = local(atom, namespace)
                if atom_name == "rPr" and i == 0:
                    properties(tree, atom, namespace, atom_name)
                elif atom_name == "t":
                    if set(atom.attrs) - {XML + "}space"} or tree.children(atom):
                        unsupported()
                    if any(c in tree.text.get(atom.path, "") for c in "\t\r\n"):
                        unsupported()
                elif atom_name in ("tab", "br", "cr"):
                    attrs(atom, namespace, {"type"} if atom_name == "br" else set())
                    if atom.attrs.get(namespace + "}type", "textWrapping") != "textWrapping":
                        unsupported()
                    if tree.children(atom):
                        unsupported()
                    tree.whitespace(atom)
                else:
                    unsupported()
            tree.whitespace(child)
            runs.append(child)
        else:
            unsupported()
    tree.whitespace(node)
    return prop, runs


def validate_lists(tree, data, source, limits):
    if not tree.list_ids:
        return
    try:
        part = load_part(data, source, "numbering", limits, FormatLimits())
        for identity in tree.list_ids:
            if (
                type(identity) is not str
                or not 1 <= len(identity) <= 10
                or not identity.isascii()
                or not identity.isdecimal()
                or not 0 < int(identity) <= 2147483647
            ):
                unsupported()
            for kind in ("bullet", "numbered"):
                try:
                    check_list(part, identity, kind)
                    break
                except FormattingError:
                    pass
            else:
                unsupported()
    except FormattingError as exc:
        raise BoundaryError(
            "boundary_limit_exceeded"
            if exc.code.endswith("limit_exceeded")
            else "unsupported_boundary"
        ) from None
