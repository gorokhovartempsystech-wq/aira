"""Detached upgrade metadata; no implicit filesystem, environment or SQL access."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

SOURCE = "0012_docx_continuous_timeout"
TARGET = "0013_docx_review_preferences"
CODES = {
    "validation_error",
    "invalid_handle",
    "upgrade_busy",
    "upgrade_unavailable",
    "upgrade_recovery_required",
    "unsupported_revision",
    "backup_limit_exceeded",
    "startup_timeout",
    "cleanup_unknown",
}


class UpgradeError(Exception):
    def __init__(self, code="upgrade_unavailable"):
        self.code = code if type(code) is str and code in CODES else "upgrade_unavailable"
        super().__init__("Local database upgrade: " + self.code)


def require(condition, code="upgrade_recovery_required"):
    if not condition:
        raise UpgradeError(code) from None


@dataclass(frozen=True)
class UpgradeTools:
    dump: Path = field(repr=False)
    restore: Path = field(repr=False)

    def __post_init__(self):
        from ara.desktop.postgres_cluster._models import checked_path

        try:
            for path, name in ((self.dump, "pg_dump"), (self.restore, "pg_restore")):
                checked_path(path)
                require(path.name == name and path.parent == self.dump.parent, "validation_error")
        except Exception:
            raise UpgradeError("validation_error") from None


@dataclass(frozen=True)
class UpgradeLimits:
    max_backup_bytes: int = 8 * 1024**3
    max_backups: int = 16
    timeout_seconds: int = 600

    def __post_init__(self):
        for value, low, high in (
            (self.max_backup_bytes, 1024, 8 * 1024**3),
            (self.max_backups, 1, 16),
            (self.timeout_seconds, 1, 600),
        ):
            require(type(value) is int and low <= value <= high, "validation_error")


@dataclass(frozen=True)
class UpgradeView:
    phase: str
    error_code: str | None
    resources_pending: bool


@dataclass(frozen=True)
class UpgradeResult:
    installation_id: UUID
    system_identifier: str
    database_oid: int
    source_revision: str | None
    target_revision: str | None
    backup_id: UUID | None = None
    backup_sha256: str | None = None
    backup_size_bytes: int | None = None


def mapped(error):
    from ara.desktop.postgres_cluster import ClusterError
    from ara.desktop.postgres_schema import SchemaError

    if isinstance(error, UpgradeError):
        return error.code
    if isinstance(error, (ClusterError, SchemaError)):
        code = error.code
        if code in ("cleanup_unknown", "startup_timeout", "invalid_handle"):
            return code
        if code.endswith("busy"):
            return "upgrade_busy"
        if code.endswith("unavailable"):
            return "upgrade_unavailable"
        return "upgrade_recovery_required"
    state = getattr(getattr(error, "orig", error), "sqlstate", None)
    return (
        "upgrade_recovery_required"
        if type(state) is str and state.startswith("42")
        else "upgrade_unavailable"
    )
