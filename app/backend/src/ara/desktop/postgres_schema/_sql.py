"""Closed transactional schema operations on an explicitly supplied connection."""

from ._models import REVISION, require


def physical(connection, cluster):
    row = connection.exec_driver_sql(
        "SELECT (SELECT system_identifier::text FROM pg_catalog.pg_control_system()),"
        "(SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=current_database()),"
        "current_database(),current_user,session_user,"
        "current_setting('server_version_num')::int,current_setting('synchronous_commit'),"
        "pg_catalog.pg_is_in_recovery()"
    ).one()
    require(
        row[0] == cluster.system_identifier
        and row[1] == cluster.database_oid
        and row[2:5] == ("aira", "aira_local", "aira_local")
        and 180000 <= row[5] < 190000
        and row[6] == "on"
        and row[7] is False
    )


def inventory(connection):
    require(
        connection.exec_driver_sql(
            "SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname NOT IN "
            "('public','pg_catalog','pg_toast','information_schema')"
        ).scalar_one()
        == 0
    )
    require(
        connection.exec_driver_sql(
            "SELECT extname FROM pg_catalog.pg_extension ORDER BY extname"
        ).all()
        == [("plpgsql",)]
    )
    for catalog, clause in (
        ("pg_proc", "obj.pronamespace=n.oid"),
        ("pg_rewrite JOIN pg_catalog.pg_class obj ON obj.oid=ev_class", "obj.relnamespace=n.oid"),
        (
            "pg_trigger JOIN pg_catalog.pg_class obj ON obj.oid=tgrelid",
            "obj.relnamespace=n.oid AND NOT tgisinternal",
        ),
    ):
        source = catalog if " JOIN " in catalog else catalog + " obj"
        require(
            connection.exec_driver_sql(
                "SELECT count(*) FROM pg_catalog."
                + source
                + " JOIN pg_catalog.pg_namespace n ON "
                + clause
                + " WHERE n.nspname='public'"
            ).scalar_one()
            == 0
        )
    require(
        connection.exec_driver_sql(
            "SELECT count(*) FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n "
            "ON n.oid=t.typnamespace WHERE n.nspname='public' AND NOT ("
            "(t.typtype='c' AND EXISTS (SELECT 1 FROM pg_catalog.pg_class c "
            "WHERE c.reltype=t.oid AND c.relkind='r')) OR "
            "(t.typtype='b' AND t.typelem<>0 AND EXISTS (SELECT 1 FROM pg_catalog.pg_type e "
            "JOIN pg_catalog.pg_class c ON c.reltype=e.oid "
            "WHERE e.oid=t.typelem AND e.typtype='c' AND c.relkind='r')))"
        ).scalar_one()
        == 0
    )
    rows = connection.exec_driver_sql(
        "SELECT relname,relkind FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY relname LIMIT 200"
    ).all()
    require(len(rows) < 200 and all(kind in ("r", "i") for _, kind in rows))
    return {name for name, kind in rows if kind == "r"}


def state(connection):
    tables = inventory(connection)
    if not tables:
        return "empty"
    require("alembic_version" in tables)
    rows = connection.exec_driver_sql(
        "SELECT version_num FROM public.alembic_version LIMIT 2"
    ).all()
    require(len(rows) == 1 and type(rows[0][0]) is str and 0 < len(rows[0][0]) <= 64)
    require(rows[0][0] == REVISION, "schema_upgrade_required")
    return "current"


def shape(connection):
    from sqlalchemy import inspect

    from ara import models  # noqa: F401 -- register current schema
    from ara.db import Base

    require(inventory(connection) == set(Base.metadata.tables) | {"alembic_version"})
    inspector = inspect(connection)
    for name, table in Base.metadata.tables.items():
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


def seed(connection, installation):
    connection.exec_driver_sql("INSERT INTO public.users(id) VALUES (%s)", (installation.user_id,))
    connection.exec_driver_sql(
        "INSERT INTO public.projects(id,owner_id,name) VALUES (%s,%s,'AIRA')",
        (installation.project_id, installation.user_id),
    )
    result = connection.exec_driver_sql(
        "UPDATE public.docx_analysis_supervisor SET phase='clean',revision=2,installation_id=%s "
        "WHERE slot_key=1 AND phase='unprovisioned' AND revision=1 AND installation_id IS NULL",
        (installation.installation_id,),
    )
    require(result.rowcount == 1)


def identities(connection, installation, *, initial):
    from ara.db import Base

    require(
        connection.exec_driver_sql("SELECT id FROM public.users LIMIT 2").all()
        == [(installation.user_id,)]
    )
    projects = connection.exec_driver_sql(
        "SELECT id,owner_id,name FROM public.projects LIMIT 2"
    ).all()
    require(
        len(projects) == 1 and projects[0][:2] == (installation.project_id, installation.user_id)
    )
    rows = connection.exec_driver_sql(
        "SELECT slot_key,revision,phase,installation_id,owner_epoch,launch_id,document_id,run_id,"
        "attempt_id,worker_instance_id,claim_fence FROM public.docx_analysis_supervisor LIMIT 2"
    ).all()
    require(len(rows) == 1)
    row = rows[0]
    require(
        row[0] == 1
        and type(row[1]) is int
        and row[1] > 0
        and row[2] in ("clean", "armed", "drained")
        and row[3] == installation.installation_id
    )
    if initial:
        require(
            projects[0][2] == "AIRA"
            and row[1:3] == (2, "clean")
            and all(value is None for value in row[4:])
        )
        for name in Base.metadata.tables:
            if name not in ("users", "projects", "docx_analysis_supervisor"):
                require(
                    not connection.exec_driver_sql(
                        "SELECT EXISTS (SELECT 1 FROM public."
                        + connection.dialect.identifier_preparer.quote(name)
                        + " LIMIT 1)"
                    ).scalar_one()
                )
