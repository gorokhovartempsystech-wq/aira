"""Immutable range requests and safe, content-free validation errors."""

from dataclasses import dataclass, field, fields

from ..projection import SourceAnchor


class RangeError(ValueError):
    """Stable diagnostics without document text, paths or parser details."""

    _MESSAGES = {
        "invalid_input": "Invalid DOCX range input or limits.",
        "range_limit_exceeded": "DOCX ranges exceed a technical limit.",
        "stale_source": "DOCX range refers to a different source version.",
        "invalid_anchor": "DOCX range does not target a projected text span.",
        "invalid_range": "DOCX range positions do not define a valid paragraph range.",
        "text_mismatch": "DOCX range expected text does not match the source.",
        "conflicting_edits": "DOCX ranges conflict in the source document.",
        "unsupported_range": "DOCX range replacement is unsupported for this content.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class TextPosition:
    """An explicit text-span anchor and local Unicode code-point offset."""

    anchor: SourceAnchor
    offset: int

    def __post_init__(self) -> None:
        anchor = getattr(self, "anchor", None)
        if type(anchor) is not SourceAnchor:
            raise RangeError("invalid_input")
        digest = getattr(anchor, "source_sha256", None)
        part = getattr(anchor, "part_name", None)
        path = getattr(anchor, "path", None)
        offset = getattr(self, "offset", None)
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or type(part) is not str
            or not part
            or type(path) is not tuple
            or any(type(index) is not int or index < 0 for index in path)
            or type(offset) is not int
            or offset < 0
        ):
            raise RangeError("invalid_input")


@dataclass(frozen=True, slots=True)
class RangeEdit:
    """Replace a source range, inheriting the explicit start span's formatting."""

    start: TextPosition
    end: TextPosition
    expected_text: str = field(repr=False)
    replacement_text: str = field(repr=False)

    def __post_init__(self) -> None:
        for name in ("start", "end"):
            position = getattr(self, name, None)
            if type(position) is not TextPosition:
                raise RangeError("invalid_input")
            position.__post_init__()
        if (
            type(getattr(self, "expected_text", None)) is not str
            or type(getattr(self, "replacement_text", None)) is not str
        ):
            raise RangeError("invalid_input")
        for char in self.replacement_text:
            point = ord(char)
            if not (
                point in (9, 10, 13)
                or 0x20 <= point <= 0xD7FF
                or 0xE000 <= point <= 0xFFFD
                or 0x10000 <= point <= 0x10FFFF
            ):
                raise RangeError("invalid_input")


@dataclass(frozen=True, slots=True)
class RangeLimits:
    """Inclusive input and unique touched-span budgets for one atomic export."""

    max_edits: int = 1000
    max_total_replacement_chars: int = 1000000
    max_touched_spans: int = 10000

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name, None)
            if type(value) is not int or value <= 0:
                raise RangeError("invalid_input")
