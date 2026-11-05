"""Detached immutable style context; never a claim of full text coverage."""

from dataclasses import dataclass, field, fields

from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-visibility/styles-context-v1"


class StyleContextError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid style-context input or limits.",
        "source_mismatch": "Style-context source hash does not match.",
        "style_limit_exceeded": "Style context exceeds a technical limit.",
    }

    def __init__(self, code: str):
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class StyleContextLimits:
    max_nodes: int = 100000
    max_depth: int = 128
    max_styles: int = 4096
    max_chain_depth: int = 128
    max_issues: int = 10000

    def __post_init__(self):
        for f in fields(self):
            if (
                type(getattr(self, f.name)) is not int
                or not 1 <= getattr(self, f.name) <= f.default
            ):
                raise StyleContextError("invalid_input")


@dataclass(frozen=True, slots=True)
class VisibilityValue:
    value: bool | None
    anchor: SourceAnchor | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class VisibilityProperties:
    vanish: VisibilityValue
    spec_vanish: VisibilityValue
    web_hidden: VisibilityValue


@dataclass(frozen=True, slots=True)
class StyleIssue:
    code: str
    anchor: SourceAnchor | None = field(repr=False)
    style_id: str | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResolvedStyle:
    style_id: str = field(repr=False)
    style_type: str
    anchor: SourceAnchor = field(repr=False)
    based_on: str | None = field(repr=False)
    is_default: bool
    status: str
    properties: VisibilityProperties | None
    issues: tuple[StyleIssue, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class StyleContext:
    source_sha256: str
    profile: str
    status: str
    styles_part: str | None = field(repr=False)
    defaults: VisibilityProperties | None
    default_paragraph_style: str | None = field(repr=False)
    default_character_style: str | None = field(repr=False)
    styles: tuple[ResolvedStyle, ...] = field(repr=False)
    issues: tuple[StyleIssue, ...] = field(repr=False)
    context_sha256: str


def absent():
    return VisibilityProperties(*(VisibilityValue(None, None) for _ in range(3)))


def budget(count, maximum):
    if count > maximum:
        raise StyleContextError("style_limit_exceeded")
