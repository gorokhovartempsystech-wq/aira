"""Transactional first schema setup with durable intent and known resource cleanup."""

import os

from ara.desktop.postgres_cluster._backend import LIBPQ_ENV
from ara.docx_analysis_worker.macos import DarwinClock

from . import _sql
from ._journal import Journal
from ._models import REVISION, SchemaError, SchemaReceipt, require


class Stopped(Exception):
    pass


class Backend:
    def __init__(self, runtime):
        self.runtime = runtime
        self.home, self.cluster = runtime._home, runtime._cluster
        self.installation = self.home.identity()
        self.identity = self.cluster.identity()
        self.clock = DarwinClock()
        self.deadline = None
        self.journal = self.engine = self.connection = self.transaction = None
        self.raw = []
        self.uncertain = False

    def check(self):
        if self.runtime._stop.is_set():
            raise Stopped()
        require(
            self.home.identity() == self.installation and self.cluster.identity() == self.identity,
            "invalid_handle",
        )
        if self.deadline is not None:
            require(self.clock.now_ns() < self.deadline, "startup_timeout")

    def connect(self):
        import psycopg

        self.check()
        require(not any(key in os.environ for key in LIBPQ_ENV), "schema_unavailable")
        try:
            raw = psycopg.connect(
                **dict(self.cluster.connection()),
                options="-c statement_timeout=60000 -c lock_timeout=1000 "
                "-c search_path=public,pg_catalog -c synchronous_commit=on",
            )
        except psycopg.OperationalError:
            raise SchemaError("schema_unavailable") from None
        except BaseException:
            self.uncertain = True
            raise SchemaError("cleanup_unknown") from None
        self.raw.append(raw)
        return raw

    def migrate(self):
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        self.check()
        cfg = Config()
        cfg.set_main_option("script_location", str(self.runtime._migrations).replace("%", "%%"))
        cfg.attributes["connection"] = self.connection
        require(
            ScriptDirectory.from_config(cfg).get_heads() == [REVISION], "schema_upgrade_required"
        )
        command.upgrade(cfg, REVISION)

    def run(self):
        from sqlalchemy import create_engine, event
        from sqlalchemy.pool import NullPool

        require(not any(key in os.environ for key in LIBPQ_ENV), "schema_unavailable")
        self.deadline = self.clock.now_ns() + 120_000_000_000
        self.check()
        self.journal = Journal(self.home, self.installation, self.identity)
        self.journal.open()
        self.check()
        self.engine = create_engine(
            "postgresql+psycopg://",
            creator=self.connect,
            poolclass=NullPool,
            hide_parameters=True,
            echo=False,
            echo_pool=False,
        )
        event.listen(self.engine, "before_cursor_execute", lambda *args: self.check())
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        _sql.physical(self.connection, self.identity)
        require(
            self.connection.exec_driver_sql(
                "SELECT pg_catalog.pg_try_advisory_xact_lock(1095911745,170302)"
            ).scalar_one()
            is True,
            "schema_busy",
        )
        state = _sql.state(self.connection)
        initial = not self.journal.completed
        if state == "empty":
            require(initial and ".ready.json.pending" not in self.journal.raw)
            self.check()
            self.journal.begin()
            self.migrate()
            _sql.seed(self.connection, self.installation)
        else:
            require(self.journal.completed or self.journal.initialized)
        _sql.shape(self.connection)
        _sql.identities(self.connection, self.installation, initial=initial)
        self.check()
        self.transaction.commit()
        self.transaction = None
        self.check()
        # COMMIT was acknowledged. Reconfirm what will be represented by the
        # durable receipt; an ACK-loss never reaches this publication step.
        _sql.physical(self.connection, self.identity)
        require(_sql.state(self.connection) == "current")
        _sql.identities(self.connection, self.installation, initial=initial)
        self.check()
        self.journal.finish()
        self.check()
        return SchemaReceipt(
            self.installation.installation_id,
            self.installation.user_id,
            self.installation.project_id,
            self.identity.system_identifier,
            self.identity.database_oid,
        )

    def close(self):
        # Only this worker owns IO. A failed close is never retried through a raw
        # descriptor or a second connection wrapper; keep the objects quarantined.
        if self.connection is not None:
            try:
                self.connection.close()
                require(self.connection.closed, "cleanup_unknown")
            except BaseException:
                self.uncertain = True
        else:
            for raw in self.raw:
                if not raw.closed:
                    try:
                        raw.close()
                        require(raw.closed, "cleanup_unknown")
                    except BaseException:
                        self.uncertain = True
        if any(not raw.closed for raw in self.raw):
            self.uncertain = True
        if self.engine is not None:
            try:
                self.engine.dispose()
            except BaseException:
                self.uncertain = True
        if self.uncertain:
            return False
        return self.journal is None or self.journal.close()
