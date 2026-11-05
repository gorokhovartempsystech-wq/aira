"""Operator-only settings from the designated secrets file, loaded explicitly."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from ara.licensing import normalize_key

from ._models import ServerError, ServerRuntime, fail, require


@dataclass(frozen=True)
class ServerSettings:
    database_url: SecretStr | str = field(repr=False)
    pepper: bytes = field(repr=False)
    issue_key: str | None = field(default=None, repr=False)

    def __post_init__(self):
        try:
            value = self.database_url
            value = value.get_secret_value() if isinstance(value, SecretStr) else value
            require(type(value) is str and 0 < len(value) <= 4096 and value == value.strip())
            require(all(ord(char) >= 32 for char in value))
            url = make_url(value)
            require(
                url.drivername == "postgresql+psycopg"
                and bool(url.database and url.database.strip())
            )
            require(url.port is None or 1 <= url.port <= 65535)
            require(type(self.pepper) is bytes and 32 <= len(self.pepper) <= 64)
            object.__setattr__(self, "database_url", SecretStr(value))
            if self.issue_key is not None:
                object.__setattr__(self, "issue_key", normalize_key(self.issue_key))
        except Exception:
            fail("validation_error")


def load_settings(*, values=None, for_issue=False):
    require(type(for_issue) is bool)
    try:
        source = (
            dotenv_values(Path.home() / "secrets.env", interpolate=False)
            if values is None
            else values
        )
        require(isinstance(source, Mapping))
        pepper = source.get("AIRA_LICENSE_PEPPER")
        require(
            type(pepper) is str and re.fullmatch(r"(?:[0-9a-fA-F]{2}){32,64}", pepper) is not None
        )
        key = normalize_key(source.get("AIRA_LICENSE_ISSUE_KEY")) if for_issue else None
        return ServerSettings(source.get("AIRA_LICENSE_DATABASE_URL"), bytes.fromhex(pepper), key)
    except ServerError:
        raise
    except Exception:
        fail("validation_error")


def create_runtime(settings):
    require(type(settings) is ServerSettings)
    checked = ServerSettings(settings.database_url, settings.pepper, settings.issue_key)
    try:
        engine = create_engine(
            checked.database_url.get_secret_value(),
            pool_size=2,
            max_overflow=0,
            pool_timeout=0.5,
            connect_args={"connect_timeout": 5},
            hide_parameters=True,
        )
    except Exception:
        fail("validation_error")
    return ServerRuntime(engine, checked.pepper)
