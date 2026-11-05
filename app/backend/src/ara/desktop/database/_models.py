"""Detached status and explicit settings carrying one process-local database source."""

from dataclasses import dataclass, field

CODES = {
    "validation_error",
    "invalid_handle",
    "database_busy",
    "database_unavailable",
    "database_mismatch",
    "cleanup_unknown",
}


class DatabaseError(Exception):
    def __init__(self, code="database_unavailable"):
        self.code = code if type(code) is str and code in CODES else "database_unavailable"
        super().__init__("Local desktop database: " + self.code)


def require(condition, code="invalid_handle"):
    if not condition:
        raise DatabaseError(code) from None


@dataclass(frozen=True)
class DatabaseView:
    phase: str
    error_code: str | None
    connections: int
    connecting: int
    resources_pending: bool


@dataclass(frozen=True)
class DesktopDatabaseSettings:
    _source: object = field(repr=False)

    def __post_init__(self):
        from ._source import DatabaseSource

        require(type(self._source) is DatabaseSource, "validation_error")
        self._source._usable()

    def validate_scope(self, *, user_id, project_id, installation_id, root):
        self._source._usable()
        identity = self._source._identity
        require(
            (user_id, project_id, installation_id, root)
            == (
                identity.user_id,
                identity.project_id,
                identity.installation_id,
                self._source._home.path("analysis"),
            ),
            "validation_error",
        )

    def create_engines(self):
        from ara.docx_analysis_worker.supervisor.database import SupervisorEngines

        self._source._usable()
        return SupervisorEngines(
            *(self._source._engine(role) for role in ("admission", "control", "publication"))
        )
