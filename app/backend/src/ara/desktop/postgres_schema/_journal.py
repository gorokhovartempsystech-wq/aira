"""Independent schema provenance; never extend the physical cluster's closed layout."""

import json
import os

from ara.desktop.postgres_cluster._filesystem import (
    FLAGS,
    Filesystem,
    directory,
    identity,
    private_file,
)

from ._models import REVISION, SchemaError, require

LOCKS = {"runtime.owner", "analysis.slot"}
RECORDS = {"initializing.json", "ready.json"}
TEMPS = {"." + name + ".pending" for name in RECORDS}


def pairs(values):
    result = {}
    for key, value in values:
        require(key not in result)
        result[key] = value
    return result


def invalid_constant(value):
    raise SchemaError("schema_recovery_required")


def record(installation, cluster, kind):
    return dict(
        schema_version="aira-schema-" + kind + "/1",
        installation_id=str(installation.installation_id),
        user_id=str(installation.user_id),
        project_id=str(installation.project_id),
        system_identifier=cluster.system_identifier,
        database_oid=cluster.database_oid,
        revision=REVISION,
    )


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


class JournalFiles(Filesystem):
    def __init__(self, root):
        super().__init__(root)
        self.parent = None

    def open(self):
        self.parent = self.walk(self.root.parent)
        directory(os.fstat(self.parent))
        try:
            os.mkdir(self.root.name, 0o700, dir_fd=self.parent)
        except FileExistsError:
            pass
        else:
            os.fsync(self.parent)
            self.full_sync(self.parent)
        self.fd = os.open(self.root.name, FLAGS, dir_fd=self.parent)
        directory(os.fstat(self.fd))
        self.key = identity(os.fstat(self.fd))
        self.entries()

    def entries(self):
        self.recheck()
        names = set()
        with os.scandir(self.fd) as entries:
            for entry in entries:
                require(entry.name in LOCKS | RECORDS | TEMPS)
                private_file(entry.stat(follow_symlinks=False), 0 if entry.name in LOCKS else 4096)
                names.add(entry.name)
        return names

    def publish(self, name, raw):
        require(name in RECORDS and type(raw) is bytes and 0 < len(raw) <= 4096)
        temp = "." + name + ".pending"
        existing = self.read(name)
        if existing is not None:
            require(existing == raw and self.read(temp) is None)
            with self.file(name, writable=True) as fd:
                self.sync(fd)
            return
        if self.read(temp) is None:
            self.recheck()
            fd = os.open(
                temp,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self.fd,
            )
            try:
                private_file(os.fstat(fd))
                offset = 0
                while offset < len(raw):
                    count = os.write(fd, raw[offset:])
                    require(
                        type(count) is int and 0 < count <= len(raw) - offset, "schema_unavailable"
                    )
                    offset += count
                os.fsync(fd)
                self.full_sync(fd)
            finally:
                self.close_fd(fd)
        else:
            require(self.read(temp) == raw)
        with self.file(temp, writable=True, publishing=True) as fd:
            os.fsync(fd)
            self.full_sync(fd)
            self.rename(temp, name)
            self.sync(fd)
            require(
                identity(os.fstat(fd))
                == identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False))
            )

    def remove(self, name, expected):
        require(name in {"initializing.json", ".initializing.json.pending"})
        require(self.read(name) == expected)
        with self.file(name, writable=True, removing=True) as fd:
            os.unlink(name, dir_fd=self.fd)
            os.fsync(self.fd)
            self.full_sync(fd)

    def close(self):
        super().close()
        parent, self.parent = self.parent, None
        self.close_fd(parent)


class Journal:
    def __init__(self, home, installation, cluster, *, revision=REVISION):
        self.fs = JournalFiles(home.path("backups") / "schema")
        self.owner = None
        self.uncertain = False
        self.expected = {
            "initializing": record(installation, cluster, "intent") | {"revision": revision},
            "ready": record(installation, cluster, "ready") | {"revision": revision},
        }
        self.raw = {}
        self.partial = None

    def open(self):
        from ara.docx_analysis_worker.macos import MacRuntimeError, acquire_owner

        self.fs.open()
        try:
            self.owner = acquire_owner(self.fs.root)
        except MacRuntimeError as error:
            if error.code == "runtime_busy":
                raise SchemaError("schema_busy") from None
            self.uncertain = True
            raise SchemaError("cleanup_unknown") from None
        slot = None
        try:
            slot = self.owner.reserve_slot()
            self.fs.bind(slot)
        except MacRuntimeError as error:
            if error.code == "runtime_busy":
                raise SchemaError("schema_busy") from None
            self.uncertain = True
            raise SchemaError("cleanup_unknown") from None
        finally:
            if slot is not None:
                try:
                    require(self.owner.release_slot(slot), "schema_busy")
                except BaseException:
                    self.uncertain = True
                    raise SchemaError("cleanup_unknown") from None
        names = self.fs.entries()
        for kind in ("initializing", "ready"):
            name, temp = kind + ".json", "." + kind + ".json.pending"
            raw, pending = self.fs.read(name), self.fs.read(temp)
            require(raw is None or pending is None)
            for key, value in ((name, raw), (temp, pending)):
                if value is None:
                    continue
                try:
                    decoded = json.loads(
                        value.decode("utf-8"),
                        object_pairs_hook=pairs,
                        parse_constant=invalid_constant,
                    )
                    require(
                        type(decoded) is dict
                        and decoded == self.expected[kind]
                        and type(decoded.get("database_oid")) is int
                    )
                except (SchemaError, ValueError, UnicodeError, RecursionError):
                    require(key == ".initializing.json.pending" and names <= LOCKS | {key})
                    self.partial = value
                    continue
                self.raw[key] = value
        require(".ready.json.pending" not in self.raw or "initializing.json" in self.raw)
        require(".initializing.json.pending" not in self.raw or len(self.raw) == 1)

    @property
    def completed(self):
        return "ready.json" in self.raw

    @property
    def initialized(self):
        return "initializing.json" in self.raw

    def begin(self):
        require(not self.completed and "ready.json" not in self.raw)
        if self.partial is not None:
            require(self.fs.entries() <= LOCKS | {".initializing.json.pending"})
            self.fs.remove(".initializing.json.pending", self.partial)
            self.partial = None
        raw = self.raw.get("initializing.json", self.raw.get(".initializing.json.pending"))
        raw = encode(self.expected["initializing"]) if raw is None else raw
        self.fs.publish("initializing.json", raw)
        self.raw.pop(".initializing.json.pending", None)
        self.raw["initializing.json"] = raw

    def finish(self):
        raw = self.raw.get("ready.json", self.raw.get(".ready.json.pending"))
        raw = encode(self.expected["ready"]) if raw is None else raw
        self.fs.publish("ready.json", raw)
        if "initializing.json" in self.raw:
            self.fs.remove("initializing.json", self.raw["initializing.json"])

    def close(self):
        if self.uncertain:
            return False
        try:
            self.fs.close()
            if self.owner is not None:
                self.owner.close()
                self.owner = None
            return True
        except BaseException:
            self.uncertain = True
            return False
