"""Durable proof of an owned upgrade and recoverable old/new receipt exchange."""

import json
from hashlib import sha256

from ara.desktop.postgres_schema._journal import encode, record

from ._files import Files, Ownership, canonical_id
from ._models import SOURCE, TARGET, require


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def decode(raw):
    require(type(raw) is bytes and 0 < len(raw) <= 4096)
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: require(False)
        )
    except (ValueError, UnicodeError, RecursionError):
        require(False)
    require(type(value) is dict)
    return value


def digest(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


class Journal(Ownership):
    def __init__(self, home, installation, cluster, *, source=SOURCE, target=TARGET):
        super().__init__(Files(home.path("backups") / "schema", {"ready.json", "upgrade.json"}))
        self.source_revision, self.target_revision = source, target
        self.target = encode(record(installation, cluster, "ready") | {"revision": target})
        self.expected_source = record(installation, cluster, "ready") | {"revision": source}
        self.binding = {
            key: value
            for key, value in self.expected_source.items()
            if key not in ("schema_version", "revision")
        }
        self.source = self.intent = self.intent_raw = None

    def source_proof(self, raw):
        value = decode(raw)
        require(value == self.expected_source and type(value["database_oid"]) is int)

    def load(self, revision):
        names = self.fs.entries()
        current = self.fs.read("ready.json")
        require(current is not None)
        intent, temp = self.fs.read("upgrade.json"), self.fs.read(".upgrade.json.pending")
        require(intent is None or temp is None)
        self.intent_raw = intent or temp
        if self.intent_raw is None:
            require(revision == self.source_revision and ".ready.json.pending" not in names)
            self.source_proof(current)
            self.source = current
            return
        value = decode(self.intent_raw)
        expected = self.binding | dict(
            schema_version="aira-schema-upgrade/1",
            source_revision=self.source_revision,
            target_revision=self.target_revision,
            backup_id=value.get("backup_id"),
            backup_sha256=value.get("backup_sha256"),
            backup_size=value.get("backup_size"),
            source_ready_sha256=value.get("source_ready_sha256"),
            target_ready_sha256=sha256(self.target).hexdigest(),
        )
        require(value == expected and type(value["database_oid"]) is int)
        require(
            canonical_id(value["backup_id"])
            and digest(value["backup_sha256"])
            and digest(value["source_ready_sha256"])
            and type(value["backup_size"]) is int
            and 0 < value["backup_size"] <= 8 * 1024**3
        )
        self.intent = value

    def begin(self, backup):
        self.intent = self.binding | dict(
            schema_version="aira-schema-upgrade/1",
            source_revision=self.source_revision,
            target_revision=self.target_revision,
            backup_id=backup["backup_id"],
            backup_sha256=backup["archive_sha256"],
            backup_size=backup["archive_size"],
            source_ready_sha256=backup["source_ready_sha256"],
            target_ready_sha256=sha256(self.target).hexdigest(),
        )
        self.intent_raw = encode(self.intent)
        self.fs.publish("upgrade.json", self.intent_raw)

    def reconcile(self, revision, source):
        self.source_proof(source)
        require(sha256(source).hexdigest() == self.intent["source_ready_sha256"])
        self.source = source
        current, temp = self.fs.read("ready.json"), self.fs.read(".ready.json.pending")
        if revision == self.source_revision:
            require(current == source and temp is None)
        else:
            require(revision == self.target_revision)
            require(
                (current == source and temp in (None, self.target))
                or (current == self.target and temp in (None, source))
            )
        self.fs.publish("upgrade.json", self.intent_raw)

    def finish(self):
        current = self.fs.read("ready.json")
        if current == self.source:
            self.fs.stage(".ready.json.pending", self.target)
            self.fs.exchange(self.source, self.target)
        else:
            require(current == self.target)
            with self.fs.file("ready.json", writable=True) as fd:
                self.fs.sync(fd)
        temp = self.fs.read(".ready.json.pending")
        if temp is not None:
            require(temp == self.source)
            self.fs.remove(".ready.json.pending", temp)
        self.fs.remove("upgrade.json", self.intent_raw)
