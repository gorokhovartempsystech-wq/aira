"""Migration entry point, executed only by an explicit Alembic command."""

from alembic import context

from ara import models  # noqa: F401 -- register tables with Base.metadata
from ara.config import load_settings
from ara.db import Base, create_database_engine


def run_with_connection(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations():
    connection = context.config.attributes.get("connection")
    if connection is not None:
        run_with_connection(connection)
        return

    settings = load_settings()
    if context.is_offline_mode():
        context.configure(
            url=settings.database_url.get_secret_value(),
            target_metadata=Base.metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            run_with_connection(connection)
    finally:
        engine.dispose()


run_migrations()
