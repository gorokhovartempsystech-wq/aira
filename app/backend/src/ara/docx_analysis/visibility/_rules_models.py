"""Bounded queries and results for ordinary-run rules, without XML claims."""

from dataclasses import dataclass, field

from ._models import StyleContextError, StyleContextLimits


class RunVisibilityError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid run-visibility input or limits.",
        "resolution_limit_exceeded": "Run visibility exceeds a technical limit.",
    }

    def __init__(self, code: str):
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class RunVisibilityQuery:
    paragraph_style_id: str | None = field(default=None, repr=False)
    character_style_id: str | None = field(default=None, repr=False)
    direct_vanish: bool | None = None
    direct_spec_vanish: bool | None = None
    direct_web_hidden: bool | None = None

    def __post_init__(self):
        for name in ("paragraph_style_id", "character_style_id"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not 1 <= len(value) <= 253):
                raise RunVisibilityError("invalid_input")
        for name in ("direct_vanish", "direct_spec_vanish", "direct_web_hidden"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise RunVisibilityError("invalid_input")


@dataclass(frozen=True, slots=True)
class RunVisibilityLimits:
    max_queries: int = 10000
    styles: StyleContextLimits = field(default_factory=StyleContextLimits)

    def __post_init__(self):
        if type(self.max_queries) is not int or not 1 <= self.max_queries <= 10000:
            raise RunVisibilityError("invalid_input")
        if type(self.styles) is not StyleContextLimits:
            raise RunVisibilityError("invalid_input")
        try:
            self.styles.__post_init__()
        except StyleContextError:
            raise RunVisibilityError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class RunVisibility:
    status: str
    code: str | None
    hidden: bool | None
    spec_vanish: bool | None
    web_hidden: bool | None


@dataclass(frozen=True, slots=True)
class RunVisibilityBatch:
    source_sha256: str
    profile: str
    policy_version: str
    context_sha256: str
    results: tuple[RunVisibility, ...] = field(repr=False)
