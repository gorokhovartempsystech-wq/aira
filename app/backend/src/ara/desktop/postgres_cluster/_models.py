"""Pure cluster configuration and detached state; no filesystem or SQL setup."""

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

_MESSAGES = {
    "validation_error": "Invalid cluster input",
    "invalid_handle": "Invalid process-local cluster",
    "platform_unavailable": "Cluster runtime is unavailable on this platform",
    "cluster_busy": "The cluster is still owned by another runtime",
    "cluster_unavailable": "The local cluster is unavailable",
    "cluster_recovery_required": "The cluster requires recovery with existing data preserved",
    "startup_timeout": "Cluster startup did not finish within its budget",
    "cleanup_unknown": "Cluster cleanup has not been confirmed",
}


class ClusterError(Exception):
    def __init__(self, code="cluster_unavailable"):
        self.code = code if type(code) is str and code in _MESSAGES else "cluster_unavailable"
        super().__init__(_MESSAGES[self.code])


def require(condition, code="cluster_recovery_required"):
    if not condition:
        raise ClusterError(code) from None


def checked_path(value):
    require(
        isinstance(value, Path) and value.is_absolute() and ".." not in value.parts,
        "validation_error",
    )
    raw = str(value)
    try:
        require(len(raw.encode("utf-8")) <= 4096, "validation_error")
    except UnicodeError:
        raise ClusterError("validation_error") from None
    require(
        not any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in raw),
        "validation_error",
    )


@dataclass(frozen=True)
class PgTools:
    target: str
    postgres: Path = field(repr=False)
    initdb: Path = field(repr=False)
    control: Path = field(repr=False)

    def __post_init__(self):
        require(
            type(self.target) is str and self.target in ("macos-arm64", "macos-x86_64"),
            "validation_error",
        )
        for path, name in (
            (self.postgres, "postgres"),
            (self.initdb, "initdb"),
            (self.control, "pg_controldata"),
        ):
            checked_path(path)
            require(path.name == name and path.parent == self.postgres.parent, "validation_error")


@dataclass(frozen=True)
class ClusterView:
    phase: str
    error_code: str | None
    resources_pending: bool


@dataclass(frozen=True)
class ClusterIdentity:
    installation_id: UUID
    system_identifier: str
    database_oid: int
    postgres_major: int = 18
