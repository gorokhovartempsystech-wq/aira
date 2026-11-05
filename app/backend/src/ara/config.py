"""Explicit database configuration; importing this module performs no setup."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class ConfigurationError(ValueError):
    """A configuration error that never includes the supplied value."""


@dataclass(frozen=True)
class DatabaseSettings:
    database_url: SecretStr | str

    def __post_init__(self) -> None:
        value = self.database_url
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        valid = False
        if isinstance(value, str) and value and value == value.strip():
            try:
                url = make_url(value)
                valid = (
                    url.drivername == "postgresql+psycopg"
                    and bool(url.database and url.database.strip())
                    and (url.port is None or 1 <= url.port <= 65535)
                )
            except (ArgumentError, ValueError, TypeError):
                pass
        if not valid:
            raise ConfigurationError(
                "ARA_DATABASE_URL must be a valid postgresql+psycopg URL with a database name"
            ) from None
        object.__setattr__(self, "database_url", SecretStr(value))


def load_settings(*, environ: Mapping[str, str] | None = None) -> DatabaseSettings:
    """Load the required setting on demand without modifying process environment.

    An explicit environment entry, even an empty one, overrides secrets.env.
    Disable dotenv interpolation so other environment values cannot be injected.
    """
    source = os.environ if environ is None else environ
    if "ARA_DATABASE_URL" in source:
        value = source["ARA_DATABASE_URL"]
    else:
        try:
            value = dotenv_values(Path.home() / "secrets.env", interpolate=False).get(
                "ARA_DATABASE_URL"
            )
        except (OSError, UnicodeError):
            raise ConfigurationError("Unable to read ARA_DATABASE_URL from ~/secrets.env") from None
    if value is None:
        raise ConfigurationError("ARA_DATABASE_URL is required")
    return DatabaseSettings(database_url=value)
