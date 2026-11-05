"""Explicit atomic initialization of an otherwise empty license database."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    inspect,
    select,
)

from ara.licensing._models import MAX_EPOCH_MS

from ._models import require, transaction

metadata = MetaData(schema="public")
schema = Table(
    "aira_license_schema",
    metadata,
    Column("id", SmallInteger, nullable=False, autoincrement=False),
    Column("revision", Integer, nullable=False),
    PrimaryKeyConstraint("id", name="pk_aira_license_schema"),
    CheckConstraint("id=1", name="ck_als_singleton"),
    CheckConstraint("revision>0", name="ck_als_revision"),
)
licenses = Table(
    "aira_licenses",
    metadata,
    Column("license_id", Uuid, nullable=False),
    Column("key_digest", String(64), nullable=False),
    Column("duration_seconds", BigInteger, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("device_id", String(68)),
    Column("activated_at_ms", BigInteger),
    Column("expires_at_ms", BigInteger),
    PrimaryKeyConstraint("license_id", name="pk_aira_licenses"),
    UniqueConstraint("key_digest", name="uq_al_key_digest"),
    CheckConstraint("license_id <> '00000000-0000-0000-0000-000000000000'::uuid", name="ck_al_id"),
    CheckConstraint("key_digest ~ '^[0-9a-f]{64}$'", name="ck_al_digest"),
    CheckConstraint(
        f"duration_seconds BETWEEN 1 AND {MAX_EPOCH_MS // 1000}", name="ck_al_duration"
    ),
    CheckConstraint(f"created_at_ms BETWEEN 0 AND {MAX_EPOCH_MS}", name="ck_al_created"),
    CheckConstraint("device_id IS NULL OR device_id ~ '^dv1-[0-9a-f]{64}$'", name="ck_al_device"),
    CheckConstraint(
        f"activated_at_ms IS NULL OR activated_at_ms BETWEEN 0 AND {MAX_EPOCH_MS}",
        name="ck_al_activated",
    ),
    CheckConstraint(
        f"expires_at_ms IS NULL OR expires_at_ms BETWEEN 0 AND {MAX_EPOCH_MS}", name="ck_al_expires"
    ),
    CheckConstraint(
        "(device_id IS NULL AND activated_at_ms IS NULL AND expires_at_ms IS NULL) OR "
        "(device_id IS NOT NULL AND activated_at_ms IS NOT NULL AND expires_at_ms IS NOT NULL "
        "AND expires_at_ms=activated_at_ms+duration_seconds*1000 "
        "AND activated_at_ms>=created_at_ms)",
        name="ck_al_binding",
    ),
)


def _relations(connection):
    return set(
        connection.exec_driver_sql(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f')"
        ).scalars()
    )


def require_schema(connection, *, full=False):
    code = "license_schema_unavailable"
    require(_relations(connection) == {table.name for table in metadata.tables.values()}, code)
    if full:
        inspector = inspect(connection)
        for table in metadata.tables.values():
            actual = {
                c["name"]: (str(c["type"]), c["nullable"])
                for c in inspector.get_columns(table.name, schema="public")
            }
            expected = {
                c.name: (c.type.compile(dialect=connection.dialect), c.nullable)
                for c in table.columns
            }
            require(actual == expected, code)
            checks = {
                c["name"] for c in inspector.get_check_constraints(table.name, schema="public")
            }
            require(
                checks == {c.name for c in table.constraints if isinstance(c, CheckConstraint)},
                code,
            )
            unique = {
                (c["name"], tuple(c["column_names"]))
                for c in inspector.get_unique_constraints(table.name, schema="public")
            }
            require(
                unique
                == {
                    (c.name, tuple(col.name for col in c.columns))
                    for c in table.constraints
                    if isinstance(c, UniqueConstraint)
                },
                code,
            )
            primary = inspector.get_pk_constraint(table.name, schema="public")
            require(
                primary["name"] == table.primary_key.name
                and primary["constrained_columns"] == [c.name for c in table.primary_key.columns],
                code,
            )
    require(connection.execute(select(schema)).all() == [(1, 1)], code)


def initialize_database(engine):
    with transaction(engine) as connection:
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(1095324225,1279873861)")
        relations = _relations(connection)
        if not relations:
            metadata.create_all(connection, checkfirst=False)
            connection.execute(schema.insert().values(id=1, revision=1))
        require_schema(connection, full=True)
