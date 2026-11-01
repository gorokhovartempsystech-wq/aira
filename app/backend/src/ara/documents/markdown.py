"""A limited, lossless Markdown splitter, not a full CommonMark parser.

Blank separators belong to the preceding block (or a leading paragraph).
Unclosed fences are preserved as unsupported blocks for explicit reporting.
"""

import re
from uuid import uuid4

_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_LIST = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])[ \t]+")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_CELL = re.compile(r":?-{3,}:?")


def _line_text(line: str) -> str:
    return line.rstrip("\r\n")


def _fence(line: str):
    match = _FENCE.fullmatch(_line_text(line))
    if match and not (match[1][0] == "`" and "`" in match[2]):
        return match[1]
    return None


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in _line_text(line).strip().strip("|").split("|")]


def _table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines) or "|" not in lines[index]:
        return False
    cells = _cells(lines[index + 1])
    return len(cells) == len(_cells(lines[index])) and all(_CELL.fullmatch(c) for c in cells)


def split_markdown(text: str) -> list[dict[str, str]]:
    """Return ordered blocks whose text concatenation equals the original input."""
    lines = text.splitlines(keepends=True)
    blocks: list[dict[str, str]] = []
    index = 0
    while index < len(lines):
        start = index
        line = lines[index]
        if not line.strip():
            if blocks:
                blocks[-1]["text"] += line
            else:
                blocks.append({"id": str(uuid4()), "kind": "paragraph", "text": line})
            index += 1
            continue

        fence = _fence(line)
        if fence:
            kind = "unsupported"
            index += 1
            closing = re.compile(
                r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*"
            )
            while index < len(lines):
                closed = closing.fullmatch(_line_text(lines[index]))
                index += 1
                if closed:
                    kind = "code"
                    break
        elif _HEADING.match(_line_text(line)):
            kind = "heading"
            index += 1
        elif _table_start(lines, index):
            kind = "table"
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                if _fence(lines[index]) or _HEADING.match(lines[index]):
                    break
                index += 1
        elif _LIST.match(line):
            kind = "list"
            index += 1
            while index < len(lines) and lines[index].strip():
                next_line = lines[index]
                if _fence(next_line) or _HEADING.match(next_line) or _table_start(lines, index):
                    break
                if not (_LIST.match(next_line) or next_line.startswith(("  ", "\t"))):
                    break
                index += 1
        else:
            kind = "paragraph"
            index += 1
            while index < len(lines) and lines[index].strip():
                next_line = lines[index]
                if (
                    _fence(next_line)
                    or _HEADING.match(_line_text(next_line))
                    or _LIST.match(next_line)
                    or _table_start(lines, index)
                ):
                    break
                index += 1
        blocks.append({"id": str(uuid4()), "kind": kind, "text": "".join(lines[start:index])})
    return blocks
