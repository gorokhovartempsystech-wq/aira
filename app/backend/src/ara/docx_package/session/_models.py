"""Public session records and content-free diagnostics."""

from dataclasses import dataclass, field, fields

from ..projection import DocxProjection


class SessionError(ValueError):
    """A stable session error without document contents or parser diagnostics."""

    _MESSAGES = {
        "invalid_input": "Invalid DOCX session input or limits.",
        "stale_revision": "DOCX session revision is no longer current.",
        "nothing_to_undo": "No DOCX session change is available to undo.",
        "nothing_to_redo": "No DOCX session change is available to redo.",
        "session_limit_exceeded": "DOCX session exceeds a technical history limit.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class SessionLimits:
    """Inclusive budgets for retained positions, including the current file."""

    max_history_states: int = 100
    max_history_bytes: int = 134217728

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name, None)
            if type(value) is not int or value <= 0:
                raise SessionError("invalid_input")


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Detached current bytes and a fresh authoritative structural projection."""

    revision: int
    data: bytes = field(repr=False)
    projection: DocxProjection = field(repr=False)
    is_dirty: bool
    undo_depth: int
    redo_depth: int
