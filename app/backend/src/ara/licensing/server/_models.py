"""Explicit server resources and sanitized failures, separate from document storage."""

from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine

from ara.licensing import LicenseError

_ERRORS = {
    "validation_error": (422, "Invalid license server input"),
    "invalid_license": (403, "License is unavailable"),
    "license_conflict": (409, "License issuance conflicts with an existing record"),
    "license_schema_unavailable": (503, "License database requires explicit preparation"),
    "license_storage_unavailable": (503, "License storage is unavailable; retry the same action"),
    "license_storage_error": (500, "Invalid stored license data"),
    "license_busy": (503, "License server is busy; retry later"),
    "https_required": (400, "A verified HTTPS connection is required"),
    "request_timeout": (408, "License request timed out"),
    "request_too_large": (413, "License request is too large"),
    "unsupported_media": (415, "JSON media is required"),
}


class ServerError(Exception):
    def __init__(self, code):
        self.code = code if type(code) is str and code in _ERRORS else "license_storage_error"
        self.status, self.message = _ERRORS[self.code]
        super().__init__(self.message)


def fail(code):
    raise ServerError(code) from None


def require(condition, code="validation_error"):
    if not condition:
        fail(code)


def validate_engine(engine):
    require(isinstance(engine, Engine))
    require(engine.dialect.name == "postgresql" and engine.dialect.driver == "psycopg")


@dataclass(frozen=True)
class ServerRuntime:
    engine: Engine = field(repr=False)
    pepper: bytes = field(repr=False)
    clock_ms: object = field(default=None, repr=False)

    def __post_init__(self):
        validate_engine(self.engine)
        require(type(self.pepper) is bytes and 32 <= len(self.pepper) <= 64)
        require(self.clock_ms is None or callable(self.clock_ms))


def validate_runtime(runtime):
    require(type(runtime) is ServerRuntime)
    runtime.__post_init__()


@contextmanager
def transaction(engine):
    validate_engine(engine)
    try:
        with engine.begin() as connection:
            version = connection.exec_driver_sql("SHOW server_version_num").scalar_one()
            require(180000 <= int(version) < 190000, "license_schema_unavailable")
            connection.exec_driver_sql("SET LOCAL search_path=pg_catalog")
            for option, value in (
                ("lock_timeout", "500ms"),
                ("statement_timeout", "2s"),
                ("idle_in_transaction_session_timeout", "2s"),
                ("transaction_timeout", "5s"),
            ):
                connection.exec_driver_sql(f"SET LOCAL {option}='{value}'")
            yield connection
    except (LicenseError, ServerError):
        raise
    except Exception:
        fail("license_storage_unavailable")
