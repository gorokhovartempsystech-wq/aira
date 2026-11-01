"""Explicit server-owned context for the local document API."""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import Engine

from ara.config import ConfigurationError


@dataclass(frozen=True, kw_only=True)
class DocumentRuntime:
    engine: Engine = field(repr=False)
    user_id: UUID
    project_id: UUID
    mode: str

    def __post_init__(self) -> None:
        if self.mode != "local":
            raise ConfigurationError("Document API requires explicit local mode")
        if not isinstance(self.engine, Engine) or not all(
            isinstance(value, UUID) for value in (self.user_id, self.project_id)
        ):
            raise ConfigurationError("Document runtime requires an engine and server-owned UUIDs")
