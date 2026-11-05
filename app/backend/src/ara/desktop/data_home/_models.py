"""Local identity and resource status, without paths or native handles in diagnostics."""

from dataclasses import dataclass
from uuid import UUID

_MESSAGES = {
    "validation_error": "Invalid application data input",
    "invalid_handle": "Application data handle is not available in this runtime",
    "home_busy": "Application data already has an owner",
    "home_unavailable": "Application data storage is unavailable",
    "home_recovery_required": "Application data requires recovery",
    "unsupported_platform": "Application data runtime is not supported on this platform",
}
CHILDREN = ("postgres", "analysis", "license", "backups")
IDENTITY = "identity.json"
PENDING = ".identity.pending"
OWNER = "runtime.owner"
ALLOWED = frozenset((*CHILDREN, IDENTITY, PENDING, OWNER))


class HomeError(Exception):
    def __init__(self, code="home_unavailable"):
        self.code = code if type(code) is str and code in _MESSAGES else "home_unavailable"
        self.message = _MESSAGES[self.code]
        super().__init__(self.message)


def require(value, code="home_recovery_required"):
    if not value:
        raise HomeError(code) from None


@dataclass(frozen=True)
class InstallationIdentity:
    installation_id: UUID
    user_id: UUID
    project_id: UUID


@dataclass(frozen=True)
class HomeView:
    phase: str
    error_code: str | None
    resources_pending: bool
