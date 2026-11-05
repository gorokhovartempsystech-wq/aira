"""Local pPr/numbering patches; old run XML and definitions stay authoritative."""

from .. import DocxError
from ..structure._xml import word_name
from ._models import FormattingError

_BEFORE_NUM = frozenset(
    ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl")
)


def escaped(value):
    return (
        value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )


def patch_bytes(raw, patches, maximum):
    # Coalesce simultaneous insertions in the caller's schema order.
    groups = {}
    for start, end, payload in patches:
        key = start, end
        if key in groups and start != end:
            raise FormattingError("unsupported_format")
        groups[key] = groups.get(key, b"") + payload
    ordered = sorted((start, end, payload) for (start, end), payload in groups.items())
    total = len(raw) + sum(len(p) - (end - start) for start, end, p in ordered)
    if total > maximum:
        raise DocxError("package_limit_exceeded")
    result, at = [], 0
    for start, end, payload in ordered:
        if start < at:
            raise FormattingError("unsupported_format")
        result.extend((raw[at:start], payload))
        at = end
    result.append(raw[at:])
    return b"".join(result)


def expand(raw, node, payload, codec):
    opening = raw[node.start : node.opening_end].decode(codec)
    if not node.empty:
        raise FormattingError("unsupported_format")
    qualified = opening[1:].split()[0].rstrip("/>")
    return (
        opening[:-2].encode(codec) + ">".encode(codec) + payload + f"</{qualified}>".encode(codec)
    )


def ppr_patch(raw, nodes, node, style_id, list_id, codec):
    namespace = node.name.rpartition("}")[0]
    style = (
        f'<aira:pStyle xmlns:aira="{namespace}" aira:val="{escaped(style_id)}"/>'
        if style_id is not None
        else ""
    ).encode(codec)
    numbering = (
        f'<aira:numPr xmlns:aira="{namespace}"><aira:ilvl aira:val="0"/>'
        f'<aira:numId aira:val="{list_id}"/></aira:numPr>'
        if list_id is not None
        else ""
    ).encode(codec)
    children = [n for p, n in nodes.items() if p[:-1] == node.path and len(p) == len(node.path) + 1]
    props = [n for n in children if word_name(n.name) == "pPr"]
    if len(props) > 1:
        raise FormattingError("unsupported_format")
    if not props:
        payload = (
            f'<aira:pPr xmlns:aira="{namespace}">'.encode(codec)
            + style
            + numbering
            + "</aira:pPr>".encode(codec)
        )
        if node.empty:
            return node.start, node.end, expand(raw, node, payload, codec)
        return node.opening_end, node.opening_end, payload
    prop = props[0]
    if prop.empty:
        return prop.start, prop.end, expand(raw, prop, style + numbering, codec)
    direct = [n for p, n in nodes.items() if p[:-1] == prop.path and len(p) == len(prop.path) + 1]
    edits = []
    for kind, payload in (("pStyle", style), ("numPr", numbering)):
        found = [n for n in direct if word_name(n.name) == kind]
        if len(found) > 1:
            raise FormattingError("unsupported_format")
        if found:
            old = found[0]
            edits.append((old.start, old.end, payload))
        elif payload:
            at = prop.opening_end
            if kind == "numPr":
                at = next(
                    (n.start for n in direct if word_name(n.name) not in _BEFORE_NUM),
                    prop.close_start,
                )
            edits.append((at, at, payload))
    local = [(start - prop.start, end - prop.start, p) for start, end, p in edits]
    payload = patch_bytes(
        raw[prop.start : prop.end], local, len(raw) * 2 + len(style) + len(numbering)
    )
    return prop.start, prop.end, payload


def new_list(namespace, abstract_id, identity, kind):
    if abstract_id > 2147483647 or identity > 2147483647:
        raise FormattingError("format_limit_exceeded")
    fmt, marker = ("bullet", "•") if kind == "bullet" else ("decimal", "%1.")
    abstract = (
        f'<aira:abstractNum xmlns:aira="{namespace}" aira:abstractNumId="{abstract_id}">'
        '<aira:multiLevelType aira:val="singleLevel"/><aira:lvl aira:ilvl="0">'
        f'<aira:start aira:val="1"/><aira:numFmt aira:val="{fmt}"/>'
        f'<aira:lvlText aira:val="{marker}"/>'
        '<aira:lvlJc aira:val="left"/><aira:pPr><aira:tabs>'
        '<aira:tab aira:val="num" aira:pos="360"/></aira:tabs>'
        '<aira:ind aira:left="360" aira:hanging="360"/></aira:pPr>'
        '<aira:rPr><aira:rFonts aira:ascii="Arial" aira:hAnsi="Arial"/></aira:rPr>'
        "</aira:lvl></aira:abstractNum>"
    )
    instance = (
        f'<aira:num xmlns:aira="{namespace}" aira:numId="{identity}">'
        f'<aira:abstractNumId aira:val="{abstract_id}"/></aira:num>'
    )
    return abstract, instance


def numbering_patch(part, definitions, maximum):
    abstracts = "".join(pair[0] for pair in definitions).encode(part.codec)
    instances = "".join(pair[1] for pair in definitions).encode(part.codec)
    if part.root.empty:
        result = expand(part.raw, part.root, abstracts + instances, part.codec)
        if len(result) > maximum:
            raise DocxError("package_limit_exceeded")
        return result
    children = part.children(part.root)
    first_num = next(
        (n.start for n in children if word_name(n.name) in ("num", "numIdMacAtCleanup")),
        part.root.close_start,
    )
    last_num = next(
        (n.start for n in children if word_name(n.name) == "numIdMacAtCleanup"),
        part.root.close_start,
    )
    return patch_bytes(
        part.raw, [(first_num, first_num, abstracts), (last_num, last_num, instances)], maximum
    )
