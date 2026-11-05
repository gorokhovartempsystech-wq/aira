"""Explicit lazy local pools; no secrets/configuration lookup at import or construction."""

import ipaddress
from dataclasses import dataclass, field

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from ara.config import DatabaseSettings

from . import _sql as db

OPTIONS = (
    "-c lock_timeout=500 -c statement_timeout=2000 "
    "-c idle_in_transaction_session_timeout=2000 -c transaction_timeout=5000 "
    "-c synchronous_commit=on"
)


@dataclass(frozen=True, slots=True)
class SupervisorEngines:
    admission: Engine = field(repr=False)
    control: Engine = field(repr=False)
    publication: Engine = field(repr=False)

    def dispose(self):
        for engine in (self.admission, self.control, self.publication):
            engine.dispose()


def create_engines(settings):
    from ara.desktop.database import DesktopDatabaseSettings

    if type(settings) is DesktopDatabaseSettings:
        return settings.create_engines()
    if type(settings) is not DatabaseSettings:
        db.fail("validation_error")
    try:
        url = make_url(settings.database_url.get_secret_value())
        if url.drivername != "postgresql+psycopg" or set(url.query) - {
            "host",
            "port",
            "connect_timeout",
        }:
            db.fail("validation_error")
        host = url.query.get("host", url.host)
        if not isinstance(host, str) or not host or "," in host:
            db.fail("validation_error")
        if "host" in url.query and url.host:
            db.fail("validation_error")
        if not host.startswith("/") and not ipaddress.ip_address(host).is_loopback:
            db.fail("validation_error")
        if "port" in url.query and (
            not str(url.query["port"]).isdigit() or not 1 <= int(url.query["port"]) <= 65535
        ):
            db.fail("validation_error")
    except (ValueError, TypeError):
        db.fail("validation_error")
    values = []
    try:
        for _ in range(3):
            values.append(
                create_engine(
                    url,
                    pool_size=1,
                    max_overflow=0,
                    pool_timeout=0.5,
                    echo=False,
                    echo_pool=False,
                    hide_parameters=True,
                    connect_args={"connect_timeout": 2, "options": OPTIONS},
                )
            )
    except Exception:
        for engine in values:
            engine.dispose()
        raise db.SupervisorStorageError("storage_error") from None
    return SupervisorEngines(*values)


def check_database(engine):
    with db.transaction(engine) as session:
        if int(session.scalar(text("SHOW server_version_num"))) < 170000:
            db.fail("recovery_required")
        for setting, expected in (
            ("fsync", "on"),
            ("full_page_writes", "on"),
            ("synchronous_commit", "on"),
            ("transaction_read_only", "off"),
            ("default_transaction_read_only", "off"),
        ):
            if session.scalar(text("SHOW " + setting)) != expected:
                db.fail("recovery_required")
        if session.scalar(text("SELECT pg_is_in_recovery()")):
            db.fail("recovery_required")
        if session.scalar(text("SELECT version_num FROM alembic_version")) not in (
            "0012_docx_continuous_timeout",
            "0013_docx_review_preferences",
        ):
            db.fail("recovery_required")
        db.locked(session)
