"""Strict source-relative commands and content-free errors."""

import re
from dataclasses import dataclass, field, fields

from ..projection import SourceAnchor


class StructureError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid DOCX structure input or limits.",
        "structure_limit_exceeded": "DOCX structure command exceeds a technical limit.",
        "stale_source": "DOCX structure command refers to a different source.",
        "invalid_anchor": "DOCX structure command does not target a body paragraph.",
        "text_mismatch": "DOCX paragraph text does not match the source.",
        "conflicting_commands": "DOCX structure commands conflict in the source.",
        "unsupported_structure": "DOCX structure operation is unsupported for this content.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


def anchor_valid(anchor):
    if type(anchor) is not SourceAnchor:
        return False
    digest, part, path = (
        getattr(anchor, "source_sha256", None),
        getattr(anchor, "part_name", None),
        getattr(anchor, "path", None),
    )
    return (
        type(digest) is str
        and re.fullmatch("[0-9a-f]{64}", digest) is not None
        and type(part) is str
        and bool(part)
        and type(path) is tuple
        and all(type(index) is int and index >= 0 for index in path)
    )


def text_valid(text):
    return type(text) is str and all(
        point in (9, 10)
        or 0x20 <= point <= 0xD7FF
        or 0xE000 <= point <= 0xFFFD
        or 0x10000 <= point <= 0x10FFFF
        for point in map(ord, text)
    )


@dataclass(frozen=True, slots=True)
class InsertParagraph:
    anchor: SourceAnchor
    expected_text: str = field(repr=False)
    texts: tuple[str, ...] = field(default=("",), repr=False)
    position: str = "after"

    def __post_init__(self):
        texts, position = getattr(self, "texts", None), getattr(self, "position", None)
        if (
            not anchor_valid(getattr(self, "anchor", None))
            or type(getattr(self, "expected_text", None)) is not str
            or type(texts) is not tuple
            or not texts
            or not all(text_valid(text) for text in texts)
            or type(position) is not str
            or position not in ("before", "after")
        ):
            raise StructureError("invalid_input")


@dataclass(frozen=True, slots=True)
class DeleteParagraph:
    anchor: SourceAnchor
    expected_text: str = field(repr=False)

    def __post_init__(self):
        if (
            not anchor_valid(getattr(self, "anchor", None))
            or type(getattr(self, "expected_text", None)) is not str
        ):
            raise StructureError("invalid_input")


@dataclass(frozen=True, slots=True)
class StructureLimits:
    max_commands: int = 1000
    max_new_paragraphs: int = 1000
    max_text_chars: int = 1000000

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name, None)
            if type(value) is not int or value <= 0:
                raise StructureError("invalid_input")
