"""Exact supported predecessor, physical identity and no active analysis."""

from ara.desktop.postgres_schema._sql import identities, inventory
from ara.desktop.postgres_schema._sql import physical as physical

from ._models import SOURCE, TARGET, require


def revision(connection, *, source=SOURCE, target=TARGET):
    tables = inventory(connection)
    if not tables:
        return None
    require("alembic_version" in tables)
    rows = connection.exec_driver_sql(
        "SELECT version_num FROM public.alembic_version LIMIT 2"
    ).all()
    require(len(rows) == 1 and type(rows[0][0]) is str)
    require(rows[0][0] in (source, target), "unsupported_revision")
    return rows[0][0]


def admission(connection, installation):
    identities(connection, installation, initial=False)
    require(
        connection.exec_driver_sql(
            "SELECT phase FROM public.docx_analysis_supervisor WHERE slot_key=1"
        ).scalar_one()
        == "clean",
        "upgrade_busy",
    )
    for name in ("docx_analysis_runs", "analysis_runs"):
        require(
            not connection.exec_driver_sql(
                "SELECT EXISTS (SELECT 1 FROM public."
                + name
                + " WHERE status IN ('queued','running','cancel_requested'))"
            ).scalar_one(),
            "upgrade_busy",
        )


def shape(connection, revision):
    from sqlalchemy import inspect

    from ara import models  # noqa: F401 -- register current schema
    from ara.db import Base

    tables = {
        name: table
        for name, table in Base.metadata.tables.items()
        if (revision == "0014_docx_file_states" or name != "docx_file_states")
        and (
            revision in (TARGET, "0014_docx_file_states")
            or name
            not in {"docx_review_preferences", "docx_review_dismissals", "docx_review_receipts"}
        )
    }
    require(inventory(connection) == set(tables) | {"alembic_version"})
    inspector = inspect(connection)
    for name, table in tables.items():
        actual = {
            c["name"]: (str(c["type"].compile(dialect=connection.dialect)), c["nullable"])
            for c in inspector.get_columns(name)
        }
        expected = {
            c.name: (str(c.type.compile(dialect=connection.dialect)), c.nullable)
            for c in table.columns
        }
        require(actual == expected)
        require(
            inspector.get_pk_constraint(name)["constrained_columns"]
            == [c.name for c in table.primary_key.columns]
        )
        observed = {
            (
                tuple(f["constrained_columns"]),
                f["referred_schema"] or "public",
                f["referred_table"],
                tuple(f["referred_columns"]),
            )
            for f in inspector.get_foreign_keys(name)
        }
        expected = {
            (
                tuple(c.name for c in f.columns),
                "public",
                f.referred_table.name,
                tuple(e.column.name for e in f.elements),
            )
            for f in table.foreign_key_constraints
        }
        require(observed == expected)
    columns = inspector.get_columns("alembic_version")
    require(
        len(columns) == 1
        and columns[0]["name"] == "version_num"
        and str(columns[0]["type"]) == "VARCHAR(32)"
        and columns[0]["nullable"] is False
    )
    require(
        inspector.get_pk_constraint("alembic_version")["constrained_columns"] == ["version_num"]
    )
