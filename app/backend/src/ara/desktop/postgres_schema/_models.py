"""Content-free schema setup metadata."""

from dataclasses import dataclass
from uuid import UUID

REVISION = "0013_docx_review_preferences"
_MESSAGES = {
    "validation_error": "Invalid schema preparation input",
    "invalid_handle": "Invalid process-local schema preparation",
    "schema_busy": "Schema preparation already has an owner",
    "schema_unavailable": "Local schema preparation is unavailable",
    "schema_recovery_required": "Existing schema data require recovery",
    "schema_upgrade_required": "Existing schema requires an explicit supported upgrade",
    "startup_timeout": "Schema preparation exceeded its startup budget",
    "cleanup_unknown": "Schema preparation cleanup has not been confirmed",
}


class SchemaError(Exception):
    def __init__(self, code="schema_unavailable"):
        self.code = code if type(code) is str and code in _MESSAGES else "schema_unavailable"
        super().__init__(_MESSAGES[self.code])


def require(condition, code="schema_recovery_required"):
    if not condition:
        raise SchemaError(code) from None


@dataclass(frozen=True)
class SchemaView:
    phase: str
    error_code: str | None
    resources_pending: bool


@dataclass(frozen=True)
class SchemaReceipt:
    installation_id: UUID
    user_id: UUID
    project_id: UUID
    system_identifier: str
    database_oid: int
    revision: str = REVISION
