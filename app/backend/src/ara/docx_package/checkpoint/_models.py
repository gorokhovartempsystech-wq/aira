"""Bounded metadata records, separate from current package and SQL identities."""

from dataclasses import dataclass
from uuid import UUID

from ..editor import EditorError, EditorSelection

MAX_REVISION = 9223372036854775807


class CheckpointError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid DOCX checkpoint metadata.",
        "checkpoint_limit_exceeded": "DOCX checkpoint metadata exceeds a technical limit.",
    }

    def __init__(self, code):
        self.code, self.message = code, self._MESSAGES[code]
        super().__init__(self.message)


def require(condition):
    if not condition:
        raise CheckpointError("invalid_input")


def integer(value, maximum=MAX_REVISION):
    require(type(value) is int and 0 <= value <= maximum)
    return value


def digest(value):
    require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value))
    return value


def selection_valid(value):
    require(type(value) is EditorSelection)
    try:
        value.__post_init__()
    except EditorError:
        raise CheckpointError("invalid_input") from None
    for caret in (value.anchor, value.focus):
        integer(caret.offset, 2147483647)
        a = caret.anchor
        require(1 <= len(a.part_name) <= 1024)
        require(
            "\x00" not in a.part_name and not any(0xD800 <= ord(c) <= 0xDFFF for c in a.part_name)
        )
        require(1 <= len(a.path) <= 128)
        for index in a.path:
            integer(index, 100000)


@dataclass(frozen=True, slots=True)
class CheckpointOrigin:
    session_id: UUID
    session_revision: int
    position_id: int

    def __post_init__(self):
        require(type(getattr(self, "session_id", None)) is UUID)
        integer(getattr(self, "session_revision", None))
        integer(getattr(self, "position_id", None))


@dataclass(frozen=True, slots=True)
class PendingSave:
    operation_id: UUID
    request_sha256: str

    def __post_init__(self):
        require(type(getattr(self, "operation_id", None)) is UUID)
        digest(getattr(self, "request_sha256", None))


@dataclass(frozen=True, slots=True, repr=False)
class CheckpointMetadata:
    selection: EditorSelection
    origin: CheckpointOrigin
    pending: PendingSave | None = None

    def __post_init__(self):
        selection_valid(getattr(self, "selection", None))
        require(type(getattr(self, "origin", None)) is CheckpointOrigin)
        self.origin.__post_init__()
        pending = getattr(self, "pending", False)
        require(pending is None or type(pending) is PendingSave)
        if pending is not None:
            pending.__post_init__()
