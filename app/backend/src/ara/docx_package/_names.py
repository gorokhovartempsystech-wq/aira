"""OPC name comparison and resolution, without accessing any URI."""

import string

from ._models import DocxError

_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
_HEX = frozenset(string.hexdigits)


def folded(value: str) -> str:
    return value.translate(_ASCII_LOWER)


def _check_uri_path(value: str) -> None:
    if not value or any(c in value for c in "\\\x00?#"):
        raise DocxError("invalid_package")
    # A URI path cannot contain raw whitespace/control characters or a scheme.
    if any(ord(c) <= 32 or ord(c) == 127 or c in '<>"{}|^`' for c in value):
        raise DocxError("invalid_package")
    if ":" in value.split("/", 1)[0]:
        raise DocxError("invalid_package")
    index = 0
    while index < len(value):
        if value[index] == "%":
            escape = value[index + 1 : index + 3]
            if len(escape) != 2 or not all(c in _HEX for c in escape):
                raise DocxError("invalid_package")
            decoded = chr(int(escape, 16))
            if decoded in _UNRESERVED or decoded in "/\\\x00":
                raise DocxError("invalid_package")
            index += 3
        else:
            index += 1


def part_key(name: str) -> str:
    """Validate a file/directory name (without a directory's trailing slash)."""
    _check_uri_path(name)
    if name.startswith("/"):
        raise DocxError("invalid_package")
    for segment in name.split("/"):
        if not segment or segment.endswith("."):
            raise DocxError("invalid_package")
        if ("[" in segment or "]" in segment) and folded(name) != "[content_types].xml":
            raise DocxError("invalid_package")
    return folded(name)


def target_key(source_part: str, target: str) -> str:
    _check_uri_path(target)
    if target.startswith("//"):
        raise DocxError("invalid_package")
    if target.startswith("/") or source_part == "/":
        segments: list[str] = []
    else:
        segments = source_part.split("/")[:-1]
    path = target[1:] if target.startswith("/") else target
    for segment in path.split("/"):
        if segment == ".":
            continue
        if segment == "..":
            if not segments:
                raise DocxError("invalid_package")
            segments.pop()
        elif not segment:
            raise DocxError("invalid_package")
        else:
            segments.append(segment)
    return part_key("/".join(segments))


def relationship_source(name: str) -> str | None:
    """Return source spelling inferred from a rels name, or None for other parts."""
    key = folded(name)
    if not key.endswith(".rels"):
        return None
    if key == "_rels/.rels":
        return "/"
    segments = name.split("/")
    if len(segments) < 2 or folded(segments[-2]) != "_rels" or segments[-1] == ".rels":
        raise DocxError("invalid_package")
    source = "/".join([*segments[:-2], segments[-1][:-5]])
    if folded(source).endswith(".rels"):
        raise DocxError("invalid_package")
    part_key(source)
    return source
