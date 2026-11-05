"""Expat element addresses plus encoding-aware, quote-aware lexical patches.

Only selected element ranges are decoded/re-encoded. The rest of the byte stream
is copied directly, including declarations, namespaces, comments and whitespace.
Input has already passed package and bounded projection validation.
"""

from xml.parsers import expat

from .. import DocxError
from ._models import EditError

_SPACE = "http://www.w3.org/XML/1998/namespace}space"
_WHITESPACE = " \t\r\n"


def _codec(data: bytes) -> str:
    # Valid declaration-free XML may begin with whitespace before its root.
    # The authoritative parser already accepted these bytes; detect the first
    # UTF-16 code unit without requiring '<' to be the first character.
    if data.startswith((b"\xff\xfe", b"<\x00", b" \x00", b"\t\x00", b"\r\x00", b"\n\x00")):
        return "utf-16-le"
    if data.startswith((b"\xfe\xff", b"\x00<", b"\x00 ", b"\x00\t", b"\x00\r", b"\x00\n")):
        return "utf-16-be"
    return "utf-8"


def _tag_end(data: bytes, start: int, codec: str) -> int:
    """Find a tag terminator, never treating quoted '>' as markup."""
    width = 1 if codec == "utf-8" else 2
    quotes = ("'".encode(codec), '"'.encode(codec))
    terminator = ">".encode(codec)
    quote = None
    for at in range(start, len(data), width):
        unit = data[at : at + width]
        if quote is not None:
            if unit == quote:
                quote = None
        elif unit in quotes:
            quote = unit
        elif unit == terminator:
            return at + width
    raise EditError("unsupported_edit")


def _opening(tag: str, space: str | None) -> tuple[str, str, bool]:
    """Retain every attribute lexeme except an existing xml:space value."""
    at = 1
    while tag[at] not in _WHITESPACE + "/>":
        at += 1
    name = tag[1:at]
    space_range = None
    while True:
        while tag[at] in _WHITESPACE:
            at += 1
        if tag[at] in "/>":
            break
        start = at
        while tag[at] not in _WHITESPACE + "=":
            at += 1
        attribute = tag[start:at]
        while tag[at] in _WHITESPACE:
            at += 1
        at += 1  # '='; the parser already validated attribute syntax.
        while tag[at] in _WHITESPACE:
            at += 1
        quote = tag[at]
        start = at + 1
        at = tag.index(quote, start)
        if attribute == "xml:space":
            space_range = (start, at)
        at += 1
    self_closing = tag.endswith("/>")
    if space_range is not None:
        if space != "preserve":
            start, end = space_range
            tag = tag[:start] + "preserve" + tag[end:]
    else:
        insert = len(tag) - (2 if self_closing else 1)
        tag = tag[:insert] + ' xml:space="preserve"' + tag[insert:]
    if self_closing:
        tag = tag[:-2] + ">"
    return tag, name, self_closing


def replace_text(data: bytes, replacements: dict[tuple[int, ...], str], limit: int) -> bytes:
    codec = _codec(data)
    parser = expat.ParserCreate(namespace_separator="}")
    # Each stack entry holds a path and its next element-child index. Comments
    # and PIs do not participate, matching the authoritative projection paths.
    stack: list[tuple[tuple[int, ...], int]] = []
    active = None
    patches: list[tuple[int, int, bytes]] = []

    def declaration(version, encoding, standalone):
        if encoding is not None and encoding.lower() not in (
            "utf-8",
            "utf8",
            "utf-16",
            "utf-16le",
            "utf-16be",
        ):
            raise EditError("unsupported_edit")

    def start(name, attributes):
        nonlocal active
        path = ()
        if stack:
            parent, index = stack[-1]
            path = parent + (index,)
            stack[-1] = (parent, index + 1)
        stack.append((path, 0))
        if path not in replacements:
            return
        offset = parser.CurrentByteIndex
        opening_end = _tag_end(data, offset, codec)
        opening, qualified, empty = _opening(
            data[offset:opening_end].decode(codec), attributes.get(_SPACE)
        )
        active = (path, offset, opening_end, opening, qualified, empty)

    def end(name):
        nonlocal active
        path, _ = stack.pop()
        if active is None or active[0] != path:
            return
        _, offset, opening_end, opening, qualified, empty = active
        text = replacements[path].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if empty:
            finish = opening_end
            closing = ("</" + qualified + ">").encode(codec)
        else:
            closing_start = parser.CurrentByteIndex
            finish = _tag_end(data, closing_start, codec)
            closing = data[closing_start:finish]
        patches.append((offset, finish, (opening + text).encode(codec) + closing))
        active = None

    def annotation(*args):
        if active is not None:
            raise EditError("unsupported_edit")

    parser.XmlDeclHandler = declaration
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CommentHandler = annotation
    parser.ProcessingInstructionHandler = annotation
    parser.Parse(data, True)
    if len(patches) != len(replacements):
        raise EditError("unsupported_edit")
    size = len(data) + sum(len(payload) - (end - start) for start, end, payload in patches)
    if size > limit:
        raise DocxError("package_limit_exceeded")
    result = []
    at = 0
    for start, end, payload in sorted(patches):
        result.extend((data[at:start], payload))
        at = end
    result.append(data[at:])
    return b"".join(result)
