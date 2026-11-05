"""Immutable internal review wire records; no runtime model or I/O."""

import re
from dataclasses import dataclass, field, fields
from uuid import UUID

from ara.docx_analysis.visible_main import VisibleLimits, VisibleViewError

VERSION = "docx-review/1"


class ReviewError(ValueError):
    MESSAGES = {
        "invalid_input": "Invalid review input or limits.",
        "unsupported_document": "Document coverage is not supported for review.",
        "empty_document": "Document has no checkable text.",
        "invalid_reply": "Invalid engine review reply.",
        "review_limit_exceeded": "Review exceeds a technical limit.",
    }

    def __init__(self, code):
        self.code = code
        self.message = self.MESSAGES[code]
        super().__init__(self.message)


def require(condition, code="invalid_reply"):
    if not condition:
        raise ReviewError(code)


def budget(count, maximum):
    require(count <= maximum, "review_limit_exceeded")


def text(value, maximum, *, empty=False, code="invalid_reply"):
    require(type(value) is str, code)
    if code == "invalid_input":
        require(len(value) <= maximum, code)
    else:
        budget(len(value), maximum)
    require(empty or bool(value.strip()), code)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ReviewError(code) from None
    return value


@dataclass(frozen=True, slots=True)
class ReviewProvenance:
    attempt_id: UUID
    execution_kind: str
    engine_version: str
    models_version: str = field(repr=False)
    model_sha256: str
    adapter_sha256: str

    def __post_init__(self):
        attempt = getattr(self, "attempt_id", None)
        require(
            type(attempt) is UUID
            and type(getattr(attempt, "int", None)) is int
            and 0 <= attempt.int < 2**128,
            "invalid_input",
        )
        kind = getattr(self, "execution_kind", None)
        require(type(kind) is str and kind in ("fixture", "local_model"), "invalid_input")
        version = getattr(self, "engine_version", None)
        require(type(version) is str and version == "0.1.0", "invalid_input")
        text(getattr(self, "models_version", None), 128, code="invalid_input")
        for name in ("model_sha256", "adapter_sha256"):
            value = getattr(self, name, None)
            require(
                type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
                "invalid_input",
            )


@dataclass(frozen=True, slots=True)
class ReviewLimits:
    max_reply_bytes: int = 4194304
    max_wire_bytes: int = 8388608
    max_issues: int = 10000
    max_questions: int = 10000
    max_metadata_characters: int = 4096
    max_suggestion_characters: int = 100000
    max_json_depth: int = 32
    view: VisibleLimits = field(default_factory=VisibleLimits)

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name, None)
            if f.name == "view":
                require(type(value) is VisibleLimits, "invalid_input")
                try:
                    value.__post_init__()
                except (VisibleViewError, AttributeError):
                    raise ReviewError("invalid_input") from None
            else:
                require(type(value) is int and 1 <= value <= f.default, "invalid_input")


def checked(provenance, limits):
    if limits is None:
        limits = ReviewLimits()
    require(type(limits) is ReviewLimits and type(provenance) is ReviewProvenance, "invalid_input")
    limits.__post_init__()
    provenance.__post_init__()
    return limits


@dataclass(frozen=True, slots=True)
class PreparedReview:
    wire_json: bytes = field(repr=False)
    engine_request_json: bytes = field(repr=False)
    request_sha256: str


@dataclass(frozen=True, slots=True)
class ReviewEnvelope:
    wire_json: bytes = field(repr=False)
    result_sha256: str
    findings_count: int
    questions_count: int
    no_findings: bool
