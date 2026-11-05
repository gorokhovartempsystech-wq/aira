"""Pure immutable metadata, not execution or filesystem authority."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

_MESSAGES = {
    "validation_error": "Invalid PostgreSQL profile input",
    "unsupported_target": "Unsupported PostgreSQL target",
    "postgres_mismatch": "PostgreSQL state does not match the owned installation",
}


class ProfileError(Exception):
    def __init__(self, code="validation_error"):
        self.code = code if type(code) is str and code in _MESSAGES else "validation_error"
        self.message = _MESSAGES[self.code]
        super().__init__(self.message)


def require(condition, code="validation_error"):
    if not condition:
        raise ProfileError(code) from None


def database_name(value):
    require(type(value) is str and value in ("aira", "postgres"))
    return value


@dataclass(frozen=True)
class PostgresPlan:
    target: str
    installation_id: UUID = field(repr=False)
    postgres_root: str = field(repr=False)
    data_dir: str = field(repr=False)
    staging_dir: str = field(repr=False)
    socket_root: str | None = field(repr=False)
    port: int
    files: Mapping[str, bytes] = field(repr=False)
    initdb_arguments: tuple[str, ...] = field(repr=False)
    postgres_arguments: tuple[str, ...] = field(repr=False)
    _system_user: str = field(repr=False)
    _windows_realm: str | None = field(repr=False)
    _expected_settings: Mapping[str, str] = field(repr=False)
    _socket_id: UUID | None = field(default=None, repr=False)

    def connection(self, database="aira"):
        from ._plan import validate_plan

        validate_plan(self)
        return MappingProxyType(
            dict(
                dbname=database_name(database),
                user="aira_local",
                host=self.socket_root if self.socket_root is not None else "127.0.0.1",
                port=str(self.port),
                connect_timeout="2",
                application_name="aira_desktop",
                sslmode="disable",
                gssencmode="disable",
                passfile="NUL" if self.target == "windows-x86_64" else "/dev/null",
            )
        )
