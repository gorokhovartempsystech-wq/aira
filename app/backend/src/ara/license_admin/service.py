"""Transactional issuance, sessions and audit in a separate PostgreSQL schema."""

import hashlib
import hmac
import re
import secrets
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    MetaData,
    String,
    Table,
    Uuid,
    case,
    inspect,
    select,
)
from sqlalchemy.dialects.postgresql import insert

from ara import licensing as core
from ara.licensing.server._models import transaction, validate_runtime
from ara.licensing.server._schema import licenses, require_schema
from ara.licensing.server._storage import _now, _record

from .security import Settings, need, verify_password

metadata = MetaData(schema="aira_license_admin")
sessions = Table(
    "sessions",
    metadata,
    Column("digest", String(64), primary_key=True),
    Column("actor", String(32), nullable=False),
    Column("revision", String(64), nullable=False),
    Column("expires_ms", BigInteger, nullable=False),
)
notes = Table(
    "notes",
    metadata,
    Column("license_id", Uuid, ForeignKey(licenses.c.license_id), primary_key=True),
    Column("label", String(120), nullable=False),
    Column("actor", String(32), nullable=False),
)
audit = Table(
    "audit",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("at_ms", BigInteger, nullable=False),
    Column("actor", String(32), nullable=False),
    Column("action", String(16), nullable=False),
    Column("license_id", Uuid),
)
attempts = Table(
    "attempts",
    metadata,
    Column("bucket", String(64), primary_key=True),
    Column("window", BigInteger, nullable=False),
    Column("count", BigInteger, nullable=False),
)
SESSION_MS = 4 * 60 * 60 * 1000
WINDOW_MS = 15 * 60 * 1000


def _schema(connection):
    checker = inspect(connection)
    need(
        set(checker.get_table_names(schema=metadata.schema))
        == {t.name for t in metadata.tables.values()},
        503,
        "admin_schema_unavailable",
    )
    for table in metadata.tables.values():
        actual = {
            c["name"]: (str(c["type"]), c["nullable"])
            for c in checker.get_columns(table.name, schema=metadata.schema)
        }
        expected = {
            c.name: (c.type.compile(dialect=connection.dialect), c.nullable) for c in table.columns
        }
        need(actual == expected, 503, "admin_schema_unavailable")
        need(
            checker.get_pk_constraint(table.name, schema=metadata.schema)["constrained_columns"]
            == [c.name for c in table.primary_key.columns],
            503,
            "admin_schema_unavailable",
        )


def initialize(engine):
    with transaction(engine) as connection:
        require_schema(connection, full=True)
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(1095324225,1094995278)")
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS aira_license_admin")
        if not inspect(connection).get_table_names(schema=metadata.schema):
            metadata.create_all(connection, checkfirst=False)
        _schema(connection)


class Service:
    def __init__(self, runtime, settings):
        validate_runtime(runtime)
        need(type(settings) is Settings)
        self.runtime, self.settings = runtime, settings

    def _event(self, connection, action, at, identifier=None):
        connection.execute(
            audit.insert().values(
                id=uuid4(),
                at_ms=at,
                actor=self.settings.username,
                action=action,
                license_id=identifier,
            )
        )

    def _session(self, connection, token, now, *, lock=True):
        need(
            type(token) is str and re.fullmatch(r"[0-9a-f]{64}", token) is not None,
            401,
            "sign_in_required",
        )
        digest = hashlib.sha256(token.encode()).hexdigest()
        query = select(sessions).where(sessions.c.digest == digest)
        if lock:
            query = query.with_for_update()
        row = connection.execute(query).mappings().one_or_none()
        need(
            row is not None
            and row["expires_ms"] > now
            and row["actor"] == self.settings.username
            and hmac.compare_digest(row["revision"], self.settings.revision),
            401,
            "sign_in_required",
        )
        return row

    def csrf(self, token):
        return self.settings.mac("csrf", token)

    def login(self, username, password, remote):
        need(type(username) is str and len(username) <= 64)
        need(type(password) is str and 1 <= len(password) <= 256)
        need(type(remote) is str and len(remote) <= 128)
        allowed = True
        with transaction(self.runtime.engine) as connection:
            require_schema(connection)
            _schema(connection)
            now = _now(connection, self.runtime)
            window = now // WINDOW_MS
            for bucket, maximum in [("global", 100), (self.settings.mac("rate", remote), 10)]:
                statement = insert(attempts).values(bucket=bucket, window=window, count=1)
                statement = statement.on_conflict_do_update(
                    index_elements=[attempts.c.bucket],
                    set_={
                        "window": window,
                        "count": case((attempts.c.window == window, attempts.c.count + 1), else_=1),
                    },
                ).returning(attempts.c.count)
                allowed = connection.scalar(statement) <= maximum and allowed
                if not allowed:
                    break
            connection.execute(attempts.delete().where(attempts.c.window < window - 1))
            connection.execute(sessions.delete().where(sessions.c.expires_ms <= now))
        need(allowed, 429, "try_later")
        matched = verify_password(password, self.settings.password)
        need(
            matched and hmac.compare_digest(username.encode(), self.settings.username.encode()),
            401,
            "invalid_login",
        )
        token = secrets.token_hex(32)
        with transaction(self.runtime.engine) as connection:
            now = _now(connection, self.runtime)
            connection.execute(
                sessions.insert().values(
                    digest=hashlib.sha256(token.encode()).hexdigest(),
                    actor=self.settings.username,
                    revision=self.settings.revision,
                    expires_ms=now + SESSION_MS,
                )
            )
            self._event(connection, "login", now)
        return token

    def state(self, token, *, offset=0):
        need(type(offset) is int and 0 <= offset <= 1000000)
        with transaction(self.runtime.engine) as connection:
            require_schema(connection)
            _schema(connection)
            now = _now(connection, self.runtime)
            self._session(connection, token, now)
            rows = (
                connection.execute(
                    select(licenses, notes.c.label)
                    .outerjoin(notes, licenses.c.license_id == notes.c.license_id)
                    .order_by(licenses.c.created_at_ms.desc(), licenses.c.license_id.desc())
                    .limit(51)
                    .offset(offset)
                )
                .mappings()
                .all()
            )
            return {
                "actor": self.settings.username,
                "csrf": self.csrf(token),
                "licenses": [self._view(row, now) for row in rows[:50]],
                "more": len(rows) > 50,
                "offset": offset,
            }

    @staticmethod
    def _view(row, now):
        record = _record(row)
        status = (
            "disabled"
            if not record.enabled
            else "unactivated"
            if record.activated_at_ms is None
            else "expired"
            if now >= record.expires_at_ms
            else "active"
        )
        return dict(
            id=str(record.license_id),
            label=row.get("label") or "Без заметки",
            days=record.duration_seconds / 86400,
            created_at_ms=row["created_at_ms"],
            activated_at_ms=record.activated_at_ms,
            expires_at_ms=record.expires_at_ms,
            status=status,
        )

    def issue(self, token, *, identifier, key, days, label):
        need(type(identifier) is str and len(identifier) == 36)
        try:
            identifier = UUID(identifier)
        except ValueError:
            need(False)
        need(identifier.int != 0)
        need(type(days) is int and 1 <= days <= 36500)
        need(
            type(label) is str
            and 1 <= len(label.strip()) <= 120
            and all(ord(c) >= 32 for c in label)
        )
        label = label.strip()
        digest = core.key_digest(key, self.runtime.pepper)
        with transaction(self.runtime.engine) as connection:
            require_schema(connection)
            _schema(connection)
            now = _now(connection, self.runtime)
            self._session(connection, token, now)
            created = connection.scalar(
                insert(licenses)
                .values(
                    license_id=identifier,
                    key_digest=digest,
                    duration_seconds=days * 86400,
                    enabled=True,
                    created_at_ms=now,
                )
                .on_conflict_do_nothing()
                .returning(licenses.c.license_id)
            )
            row = (
                connection.execute(
                    select(licenses).where(licenses.c.license_id == identifier).with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            need(
                row is not None
                and row["key_digest"] == digest
                and row["duration_seconds"] == days * 86400,
                409,
                "issuance_conflict",
            )
            existing = (
                connection.execute(select(notes).where(notes.c.license_id == identifier))
                .mappings()
                .one_or_none()
            )
            if existing is None:
                # A new ID must not adopt an older license created outside this panel.
                need(created is not None, 409, "issuance_conflict")
                connection.execute(
                    notes.insert().values(
                        license_id=identifier, label=label, actor=self.settings.username
                    )
                )
                self._event(connection, "issue", now, identifier)
            else:
                need(
                    existing["label"] == label and existing["actor"] == self.settings.username,
                    409,
                    "issuance_conflict",
                )
            return self._view(dict(row) | {"label": label}, now)

    def disable(self, token, identifier):
        try:
            identifier = UUID(identifier)
        except (ValueError, TypeError):
            need(False)
        with transaction(self.runtime.engine) as connection:
            require_schema(connection)
            _schema(connection)
            now = _now(connection, self.runtime)
            self._session(connection, token, now)
            row = (
                connection.execute(
                    select(licenses).where(licenses.c.license_id == identifier).with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            need(row is not None, 404, "not_found")
            if row["enabled"]:
                connection.execute(
                    licenses.update()
                    .where(licenses.c.license_id == identifier)
                    .values(enabled=False)
                )
                self._event(connection, "disable", now, identifier)

    def logout(self, token):
        with transaction(self.runtime.engine) as connection:
            now = _now(connection, self.runtime)
            row = self._session(connection, token, now)
            connection.execute(sessions.delete().where(sessions.c.digest == row["digest"]))
            self._event(connection, "logout", now)
