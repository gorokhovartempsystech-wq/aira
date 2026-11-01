"""Source-bound cursor records without document text in diagnostics."""

from dataclasses import dataclass, field

from ..projection import SourceAnchor
from ..session import SessionSnapshot
from ..structure._models import anchor_valid


class EditorError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid DOCX editor input.",
        "invalid_selection": "DOCX selection does not target a valid body position.",
        "stale_selection": "DOCX selection refers to a different source.",
        "unsupported_intent": "DOCX editor intent is unsupported for this selection or style.",
        "text_limit_exceeded": "DOCX text insertion exceeds a technical limit.",
    }

    def __init__(self, code):
        self.code, self.message = code, self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class PasteLimits:
    max_text_chars: int = 1000000
    max_new_paragraphs: int = 1000

    def __post_init__(self):
        if any(
            type(getattr(self, name, None)) is not int or getattr(self, name) <= 0
            for name in ("max_text_chars", "max_new_paragraphs")
        ):
            raise EditorError("invalid_input")


def _point(value, name):
    return type(getattr(value, name, None)) is int and getattr(value, name) >= 0


def _affinity(value):
    return type(getattr(value, "affinity", None)) is str and value.affinity in ("left", "right")


@dataclass(frozen=True, slots=True)
class Caret:
    anchor: SourceAnchor
    offset: int
    affinity: str = "right"

    def __post_init__(self):
        if (
            not anchor_valid(getattr(self, "anchor", None))
            or not _point(self, "offset")
            or not _affinity(self)
        ):
            raise EditorError("invalid_input")


@dataclass(frozen=True, slots=True)
class CaretTarget:
    block_index: int
    offset: int
    affinity: str = "right"

    def __post_init__(self):
        if not _point(self, "block_index") or not _point(self, "offset") or not _affinity(self):
            raise EditorError("invalid_input")


@dataclass(frozen=True, slots=True)
class EditorSelection:
    anchor: Caret
    focus: Caret

    def __post_init__(self):
        for name in ("anchor", "focus"):
            value = getattr(self, name, None)
            if type(value) is not Caret:
                raise EditorError("invalid_input")
            value.__post_init__()


@dataclass(frozen=True, slots=True)
class SelectionTarget:
    anchor: CaretTarget
    focus: CaretTarget

    def __post_init__(self):
        for name in ("anchor", "focus"):
            value = getattr(self, name, None)
            if type(value) is not CaretTarget:
                raise EditorError("invalid_input")
            value.__post_init__()


@dataclass(frozen=True, slots=True)
class EditorSnapshot:
    document: SessionSnapshot = field(repr=False)
    selection: EditorSelection = field(repr=False)
    position_id: int

    def __post_init__(self):
        if (
            type(self.document) is not SessionSnapshot
            or type(self.selection) is not EditorSelection
            or not _point(self, "position_id")
        ):
            raise EditorError("invalid_input")
        self.selection.__post_init__()
