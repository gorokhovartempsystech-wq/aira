"""Validated records and content-free diagnostics for anchored text replacement."""

from dataclasses import dataclass, field, fields

from ..projection import SourceAnchor


class EditError(ValueError):
    """Stable diagnostics that never incorporate client or document content."""

    _MESSAGES = {
        "invalid_input": "Invalid DOCX edit input or limits.",
        "edit_limit_exceeded": "DOCX edits exceed a technical limit.",
        "stale_source": "DOCX edit refers to a different source version.",
        "invalid_anchor": "DOCX edit does not target a projected text span.",
        "text_mismatch": "DOCX edit expected text does not match the source.",
        "duplicate_edit": "DOCX edits contain a duplicate target.",
        "unsupported_edit": "DOCX text replacement is unsupported for this content.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class TextEdit:
    """Replace one entire projected text span in an exact source version."""

    anchor: SourceAnchor
    expected_text: str = field(repr=False)
    replacement_text: str = field(repr=False)

    def __post_init__(self) -> None:
        anchor = getattr(self, "anchor", None)
        if type(anchor) is not SourceAnchor:
            raise EditError("invalid_input")
        digest = getattr(anchor, "source_sha256", None)
        part = getattr(anchor, "part_name", None)
        path = getattr(anchor, "path", None)
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or type(part) is not str
            or not part
            or type(path) is not tuple
            or any(type(index) is not int or index < 0 for index in path)
            or type(getattr(self, "expected_text", None)) is not str
            or type(getattr(self, "replacement_text", None)) is not str
        ):
            raise EditError("invalid_input")
        for char in self.replacement_text:
            point = ord(char)
            if not (
                point in (9, 10, 13)
                or 0x20 <= point <= 0xD7FF
                or 0xE000 <= point <= 0xFFFD
                or 0x10000 <= point <= 0x10FFFF
            ):
                raise EditError("invalid_input")


@dataclass(frozen=True, slots=True)
class EditLimits:
    """Inclusive call budgets, also counting unchanged replacements."""

    max_edits: int = 1000
    max_total_replacement_chars: int = 1000000

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name, None)
            if type(value) is not int or value <= 0:
                raise EditError("invalid_input")
