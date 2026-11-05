"""Strict source-relative full paragraph format commands."""

import re
from dataclasses import dataclass, field, fields

from ..projection import SourceAnchor
from ..structure._models import anchor_valid, text_valid


class FormattingError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid DOCX format input or limits.",
        "format_limit_exceeded": "DOCX formatting exceeds a technical limit.",
        "stale_source": "DOCX format refers to a different source.",
        "invalid_anchor": "DOCX format does not target a body paragraph.",
        "text_mismatch": "DOCX paragraph text does not match the source.",
        "conflicting_formats": "DOCX format commands target the same paragraph.",
        "unsupported_format": "DOCX format is unsupported for this content.",
    }

    def __init__(self, code):
        self.code, self.message = code, self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class ParagraphFormat:
    anchor: SourceAnchor
    expected_text: str = field(repr=False)
    style_id: str | None = None
    list_kind: str = "none"
    list_id: str | None = None

    def __post_init__(self):
        style, kind, identity = (
            getattr(self, "style_id", None),
            getattr(self, "list_kind", None),
            getattr(self, "list_id", None),
        )
        if (
            not anchor_valid(getattr(self, "anchor", None))
            or type(getattr(self, "expected_text", None)) is not str
            or (
                style is not None
                and (
                    not text_valid(style)
                    or not 1 <= len(style) <= 255
                    or any(c in style for c in "\t\n")
                )
            )
            or type(kind) is not str
            or kind not in ("none", "bullet", "numbered")
            or (
                identity is not None
                and (
                    type(identity) is not str
                    or re.fullmatch(r"[1-9][0-9]{0,9}", identity) is None
                    or int(identity) > 2147483647
                )
            )
            or (kind == "none" and identity is not None)
        ):
            raise FormattingError("invalid_input")


@dataclass(frozen=True, slots=True)
class FormatLimits:
    max_formats: int = 1000
    max_aux_nodes: int = 100000
    max_aux_depth: int = 128

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name, None)
            if type(value) is not int or value <= 0:
                raise FormattingError("invalid_input")
