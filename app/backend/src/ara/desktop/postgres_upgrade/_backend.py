"""Snapshot, retained backup, transactional migration and durable receipt reconciliation."""

import os
import re
from uuid import UUID

from ara.desktop.postgres_cluster._backend import LIBPQ_ENV
from ara.desktop.postgres_cluster._filesystem import directory, identity
from ara.desktop.postgres_schema._backend import Backend as SchemaBackend
from ara.desktop.postgres_schema._backend import Stopped  # noqa: F401 -- shared stop signal

from . import _sql
from ._backup import Backup
from ._files import Files
from ._journal import Journal
from ._models import SOURCE, TARGET, UpgradeResult, require


class Backend(SchemaBackend):
    def __init__(self, runtime):
        super().__init__(runtime)
        self.backup = self.probe = None
        self.source_revision = getattr(runtime, "_source", SOURCE)
        self.policy_options = (
            {}
            if self.revision == TARGET
            else {"source": self.source_revision, "target": self.revision}
        )

    def phase(self, phase):
        self.check()
        with self.runtime._lock:
            self.runtime._phase = phase

    def pending(self):
        # No-op must not create a backup/schema directory on a first launch.
        fs = self.probe = Files(self.home.path("backups") / "schema", set())
        try:
            fs.fd = fs.walk(fs.root)
        except FileNotFoundError:
            return False
        directory(os.fstat(fs.fd))
        fs.key = identity(os.fstat(fs.fd))
        return fs.read("upgrade.json") is not None or fs.read(".upgrade.json.pending") is not None

    def run(self):
        from sqlalchemy import create_engine, event
        from sqlalchemy.pool import NullPool

        require(not any(key in os.environ for key in LIBPQ_ENV), "upgrade_unavailable")
        self.deadline = self.clock.now_ns() + self.runtime._limits.timeout_seconds * 1_000_000_000
        self.check()
        self.engine = create_engine(
            "postgresql+psycopg://",
            creator=self.connect,
            poolclass=NullPool,
            hide_parameters=True,
            echo=False,
            echo_pool=False,
            isolation_level="REPEATABLE READ",
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
            "upgrade_busy",
        )
        revision = _sql.revision(self.connection, **self.policy_options)
        if not self.pending() and revision in (None, self.revision):
            return UpgradeResult(
                self.installation.installation_id,
                self.identity.system_identifier,
                self.identity.database_oid,
                revision,
                revision,
            )
        require(revision in (self.source_revision, self.revision))
        self.journal = Journal(self.home, self.installation, self.identity, **self.policy_options)
        self.journal.open()
        self.journal.load(revision)
        _sql.shape(self.connection, revision)
        _sql.admission(self.connection, self.installation)
        self.phase("backing_up")
        self.backup = Backup(self)
        self.backup.open()
        if self.journal.intent is not None:
            source, metadata = self.backup.recover(self.journal.intent)
            self.journal.reconcile(revision, source)
        else:
            snapshot = self.connection.exec_driver_sql(
                "SELECT pg_catalog.pg_export_snapshot()"
            ).scalar_one()
            require(
                type(snapshot) is str
                and len(snapshot) <= 128
                and re.fullmatch(r"[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+", snapshot) is not None
            )
            metadata = self.backup.create(self.journal.source, snapshot)
            self.check()
            self.journal.begin(metadata)
        if revision == self.source_revision:
            self.phase("migrating")
            self.migrate()
            require(_sql.revision(self.connection, **self.policy_options) == self.revision)
            _sql.shape(self.connection, self.revision)
            _sql.admission(self.connection, self.installation)
        self.check()
        self.transaction.commit()
        self.transaction = None
        self.check()
        _sql.physical(self.connection, self.identity)
        require(_sql.revision(self.connection, **self.policy_options) == self.revision)
        _sql.admission(self.connection, self.installation)
        self.phase("publishing")
        self.journal.finish()
        self.check()
        return UpgradeResult(
            self.installation.installation_id,
            self.identity.system_identifier,
            self.identity.database_oid,
            self.source_revision,
            self.revision,
            UUID(metadata["backup_id"]),
            metadata["archive_sha256"],
            metadata["archive_size"],
        )

    def close(self):
        if self.backup is not None and not self.backup.close():
            return False
        if not super().close():
            return False
        try:
            if self.probe is not None:
                self.probe.close()
            return True
        except BaseException:
            self.uncertain = True
            return False
