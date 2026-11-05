"""Full custom archive on an exported SQL snapshot, retained across every failure."""

import os
import re
import time
from hashlib import sha256
from uuid import uuid4

from ara.desktop.postgres_cluster._filesystem import identity, private_file, stamp
from ara.desktop.postgres_process import OwnedCommand
from ara.desktop.postgres_schema._journal import encode

from ._files import Files, Ownership, canonical_id
from ._journal import decode, digest
from ._models import SOURCE, require


class Backup(Ownership):
    def __init__(self, backend):
        super().__init__(Files(backend.home.path("backups") / "postgres", set(), backups=True))
        self.backend = backend
        self.limits = backend.runtime._limits
        self.bundle = self.command = None
        self.archive_fd = None
        self.archive_key = None
        self.binding = backend.journal.binding | {
            "source_revision": getattr(backend.journal, "source_revision", SOURCE)
        }

    def run_command(self, executable, args, *, capture=False, monitor=None):
        self.backend.check()
        self.command = OwnedCommand(
            self.owner, executable, tuple(args), cwd=self.fs.root, capture_stdout=capture
        )
        self.command.start()
        while self.command.view().resources_pending:
            self.backend.check()
            if monitor is not None:
                monitor()
            time.sleep(0.01)
        self.backend.check()
        state = self.command.view()
        require(state.phase == "exited" and state.returncode == 0, "upgrade_unavailable")
        result = self.command.stdout() if capture else None
        self.command = None
        return result

    def versions(self):
        for path in (self.backend.runtime._tools.dump, self.backend.runtime._tools.restore):
            output = self.run_command(path, ("--version",), capture=True)
            require(
                re.fullmatch(
                    rb"pg_(?:dump|restore) \(PostgreSQL\) 18(?:\.[0-9]+)?[^\r\n]*\n", output
                )
                is not None,
                "upgrade_unavailable",
            )

    def select(self, name, *, create=False):
        require(canonical_id(name))
        names = self.fs.entries()
        copies = {value for value in names if canonical_id(value)}
        require(len(copies) <= self.limits.max_backups, "backup_limit_exceeded")
        if create:
            require(len(copies) < self.limits.max_backups, "backup_limit_exceeded")
            self.fs.recheck()
            os.mkdir(name, 0o700, dir_fd=self.fs.fd)
            os.fsync(self.fs.fd)
            self.fs.full_sync(self.fs.fd)
        else:
            require(name in copies)
        self.bundle = Files(
            self.fs.root / name,
            {"intent.json", "schema-before.json", "backup.json"},
            max_bytes=self.limits.max_backup_bytes,
        )
        self.bundle.open()

    def open_archive(self, name, *, create=False):
        fs = self.bundle
        fs.recheck()
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        try:
            self.archive_fd = os.open(name, flags, 0o600, dir_fd=fs.fd)
        except FileNotFoundError:
            require(False, "upgrade_unavailable" if create else "upgrade_recovery_required")
        self.archive_key = identity(os.fstat(self.archive_fd))
        self.archive_info(name)

    def archive_info(self, name):
        self.bundle.recheck()
        info = os.fstat(self.archive_fd)
        require(info.st_size <= self.limits.max_backup_bytes, "backup_limit_exceeded")
        private_file(info, self.limits.max_backup_bytes)
        require(identity(info) == self.archive_key)
        named = os.stat(name, dir_fd=self.bundle.fd, follow_symlinks=False)
        require(named.st_size <= self.limits.max_backup_bytes, "backup_limit_exceeded")
        private_file(named, self.limits.max_backup_bytes)
        require(identity(info) == identity(named))
        return info

    def hashed(self, name):
        self.backend.check()
        before = self.archive_info(name)
        os.lseek(self.archive_fd, 0, os.SEEK_SET)
        total, digestor = 0, sha256()
        while True:
            self.backend.check()
            chunk = os.read(self.archive_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            require(total <= self.limits.max_backup_bytes, "backup_limit_exceeded")
            digestor.update(chunk)
        after = self.archive_info(name)
        require(stamp(before) == stamp(after) and total == after.st_size and total > 0)
        return digestor.hexdigest(), total

    def toc(self, name):
        before = stamp(self.archive_info(name))
        self.run_command(
            self.backend.runtime._tools.restore,
            ("--list", str(self.bundle.root / name)),
            capture=True,
        )
        require(before == stamp(self.archive_info(name)))

    def create(self, source, snapshot):
        from psycopg.conninfo import make_conninfo

        self.versions()
        required = self.backend.connection.exec_driver_sql(
            "SELECT pg_catalog.pg_database_size(current_database())"
        ).scalar_one()
        space = os.fstatvfs(self.fs.fd)
        require(
            space.f_bavail * space.f_frsize >= max(required * 2, 1024 * 1024),
            "backup_limit_exceeded",
        )
        name = str(uuid4())
        self.select(name, create=True)
        intent = self.binding | dict(
            schema_version="aira-pg-backup-intent/1",
            backup_id=name,
            source_ready_sha256=sha256(source).hexdigest(),
        )
        self.bundle.publish("intent.json", encode(intent))
        self.bundle.publish("schema-before.json", source)
        self.open_archive("data.dump.pending", create=True)
        self.run_command(
            self.backend.runtime._tools.dump,
            (
                "--format=custom",
                "--no-password",
                "--lock-wait-timeout=2s",
                "--snapshot=" + snapshot,
                "--dbname=" + make_conninfo(**dict(self.backend.cluster.connection())),
                "--file=" + str(self.bundle.root / "data.dump.pending"),
            ),
            monitor=lambda: self.archive_info("data.dump.pending"),
        )
        hashed, size = self.hashed("data.dump.pending")
        self.toc("data.dump.pending")
        self.backend.check()
        self.bundle.sync(self.archive_fd)
        self.bundle.rename("data.dump.pending", "data.dump")
        self.archive_info("data.dump")
        self.bundle.sync(self.archive_fd)
        metadata = intent | dict(
            schema_version="aira-pg-backup/1",
            archive_sha256=hashed,
            archive_size=size,
            postgres_major=18,
        )
        self.bundle.publish("backup.json", encode(metadata))
        require(self.bundle.read("backup.json") == encode(metadata))
        require(self.hashed("data.dump") == (hashed, size))
        return metadata

    def recover(self, upgrade):
        self.versions()
        self.select(upgrade["backup_id"])
        source = self.bundle.read("schema-before.json")
        self.backend.journal.source_proof(source)
        expected_intent = self.binding | dict(
            schema_version="aira-pg-backup-intent/1",
            backup_id=upgrade["backup_id"],
            source_ready_sha256=upgrade["source_ready_sha256"],
        )
        intent = decode(self.bundle.read("intent.json"))
        require(intent == expected_intent and type(intent["database_oid"]) is int)
        expected = expected_intent | dict(
            schema_version="aira-pg-backup/1",
            archive_sha256=upgrade["backup_sha256"],
            archive_size=upgrade["backup_size"],
            postgres_major=18,
        )
        metadata = decode(self.bundle.read("backup.json"))
        require(
            metadata == expected
            and type(metadata["archive_size"]) is int
            and type(metadata["database_oid"]) is int
            and type(metadata["postgres_major"]) is int
        )
        require(
            digest(metadata["archive_sha256"])
            and sha256(source).hexdigest() == metadata["source_ready_sha256"]
        )
        self.open_archive("data.dump")
        require(self.hashed("data.dump") == (metadata["archive_sha256"], metadata["archive_size"]))
        self.toc("data.dump")
        return source, metadata

    def close(self):
        # Stop remains pending until the owned guardian/child and inherited slot
        # have a known outcome. Never force-kill or recycle a numeric descriptor.
        if self.command is not None:
            while not self.command.shutdown(0.1):
                if self.command.view().error_code == "cleanup_unknown":
                    self.uncertain = True
                    return False
        if self.uncertain:
            return False
        try:
            if self.bundle is not None:
                fd, self.archive_fd = self.archive_fd, None
                self.bundle.close_fd(fd)
                self.bundle.close()
            return super().close()
        except BaseException:
            self.uncertain = True
            return False
