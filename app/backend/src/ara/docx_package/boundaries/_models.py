"""Strict boundary commands and content-free diagnostics."""

from dataclasses import dataclass, field

from ..projection import SourceAnchor
from ..structure._models import anchor_valid


class BoundaryError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid DOCX boundary input or limits.",
        "boundary_limit_exceeded": "DOCX boundary exceeds a technical limit.",
        "stale_source": "DOCX boundary refers to a different source.",
        "invalid_anchor": "DOCX boundary does not target a body paragraph.",
        "invalid_position": "DOCX split position is outside the paragraph.",
        "text_mismatch": "DOCX boundary text does not match the source.",
        "nonadjacent_paragraphs": "DOCX join requires two adjacent ordered paragraphs.",
        "incompatible_paragraph_format": "DOCX paragraphs have incompatible formatting.",
        "unsupported_boundary": "DOCX boundary operation is unsupported for this content.",
    }

    def __init__(self, code):
        self.code, self.message = code, self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class SplitParagraph:
    anchor: SourceAnchor
    expected_text: str = field(repr=False)
    offset: int

    def __post_init__(self):
        if (
            not anchor_valid(getattr(self, "anchor", None))
            or type(getattr(self, "expected_text", None)) is not str
            or type(getattr(self, "offset", None)) is not int
            or self.offset < 0
        ):
            raise BoundaryError("invalid_input")


@dataclass(frozen=True, slots=True)
class JoinParagraphs:
    left_anchor: SourceAnchor
    right_anchor: SourceAnchor
    expected_left_text: str = field(repr=False)
    expected_right_text: str = field(repr=False)

    def __post_init__(self):
        if any(
            not anchor_valid(getattr(self, n, None)) for n in ("left_anchor", "right_anchor")
        ) or any(
            type(getattr(self, n, None)) is not str
            for n in ("expected_left_text", "expected_right_text")
        ):
            raise BoundaryError("invalid_input")


@dataclass(frozen=True, slots=True)
class BoundaryLimits:
    max_touched_nodes: int = 10000

    def __post_init__(self):
        if type(getattr(self, "max_touched_nodes", None)) is not int or self.max_touched_nodes <= 0:
            raise BoundaryError("invalid_input")
