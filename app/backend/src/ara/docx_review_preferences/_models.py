"""Detached preference/receipt records, never authorization capabilities."""

from dataclasses import dataclass, field
from uuid import UUID

from ara.documents.storage import DocumentError

MAX_REVISION = 2**63 - 1
MAX_HIDDEN = 10000
TYPES = ("contradiction", "duplicate", "formulation")


def fail(code):
    status, message = {
        "validation_error": (422, "Invalid review preference command"),
        "not_found": (404, "Document, analysis or finding not found"),
        "preferences_conflict": (409, "Review preferences or result have changed"),
        "idempotency_conflict": (409, "Review preference command does not match"),
        "result_not_ready": (409, "Analysis result is not ready"),
        "preferences_history_exhausted": (409, "Review preference history counter is exhausted"),
        "preferences_limit_exceeded": (413, "Review preferences exceed a technical limit"),
        "storage_error": (500, "Review preference storage operation failed"),
        "storage_unavailable": (503, "Review preference storage is unavailable"),
        "preferences_schema_unavailable": (503, "Review preference schema is unavailable"),
    }[code]
    raise DocumentError(status, code, message, status == 503) from None


def require(condition, code="validation_error"):
    if not condition:
        fail(code)


@dataclass(frozen=True, slots=True)
class PreferencesState:
    document_id: UUID
    revision: int
    disabled_types: tuple[str, ...]
    show_questions: bool
    show_hidden: bool
    hidden_keys: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreferenceReceipt:
    document_id: UUID
    command_id: UUID
    kind: str
    expected_revision: int
    revision: int
    changed: bool


@dataclass(frozen=True, slots=True)
class Command:
    document_id: UUID
    command_id: UUID
    expected_revision: int
    kind: str
    values: dict = field(repr=False)
    data: bytes = field(repr=False)
    sha256: str


@dataclass(frozen=True, slots=True)
class Origin:
    run_id: UUID
    source: object = field(repr=False)
    attempt: object = field(repr=False)
    result: object = field(repr=False)
