"""Database primitives with explicit, lazy engine construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase

from ara.config import DatabaseSettings


class Base(DeclarativeBase):
    pass


def create_database_engine(settings: DatabaseSettings) -> Engine:
    """Construct a pool; the first connect/begin opens the database connection."""
    return create_engine(
        settings.database_url.get_secret_value(),
        echo=False,
        echo_pool=False,
        hide_parameters=True,
    )
