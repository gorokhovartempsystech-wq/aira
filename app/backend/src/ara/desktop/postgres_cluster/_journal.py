"""First-run journal; only a proven unfinished initialization can create data."""

from pathlib import Path
from uuid import uuid4

from . import _records
from ._filesystem import CONFIGS, DATA, LOCKS, STAGE, retained
from ._models import ClusterError, require


def load(backend):
    fs, installation, target = backend.fs, backend.installation, backend.tools.target
    names = fs.entries()
    records, pending = {}, {}
    for kind in ("initialization", "prepared", "cluster"):
        name = kind + ".json"
        temp = "." + name + ".pending"
        raw, partial = fs.read(name), fs.read(temp)
        require(raw is None or partial is None)
        if raw is not None:
            records[kind] = _records.decode(raw, kind, installation, target)
        if partial is not None:
            try:
                pending[kind] = _records.decode(partial, kind, installation, target)
            except ClusterError:
                # A truncated initial intent is replaceable only in an otherwise
                # pristine directory. No data, prepared proof or configs exist.
                require(kind == "initialization" and names <= LOCKS | {temp})
                fs.remove(temp, partial)
                continue
    if "cluster" in pending:
        require(
            DATA in names
            and STAGE not in names
            and "initialization" in records
            and "prepared" in records
        )
        require(pending["cluster"]["system_identifier"] == records["prepared"]["system_identifier"])
    if "prepared" in pending:
        require(
            "initialization" in records
            and "cluster" not in records
            and (DATA in names) != (STAGE in names)
        )
    if "initialization" in pending:
        require(names <= LOCKS | {".initialization.json.pending"})
    for kind, value in pending.items():
        backend.check()
        name = kind + ".json"
        fs.publish(name, fs.read("." + name + ".pending"))
        records[kind] = value
    return records


def prepare(backend):
    fs = backend.fs
    records = load(backend)
    names = fs.entries()
    final, prepared, intent = (
        records.get(key) for key in ("cluster", "prepared", "initialization")
    )
    if final is not None:
        require(DATA in names and STAGE not in names)
        if prepared is not None:
            require(prepared["system_identifier"] == final["system_identifier"])
        expected, first = final["system_identifier"], False
    else:
        if intent is None:
            require(names <= LOCKS)
            intent = _records.make("initialization", backend.installation, backend.tools.target)
            backend.check()
            fs.publish("initialization.json", _records.encode(intent))
        require(not (DATA in names and STAGE in names))
        if prepared is None:
            require(DATA not in names)
            if STAGE in names:
                require(sum(retained(name) for name in names) < 3)
                backend.check()
                fs.move_directory(STAGE, "failed-init-" + str(uuid4()))
            backend.check()
            backend.run_command(backend.tools.initdb, backend.plan.initdb_arguments)
            expected = control(backend, STAGE, initial=True)
            prepared = _records.make(
                "prepared", backend.installation, backend.tools.target, expected
            )
            backend.check()
            fs.publish("prepared.json", _records.encode(prepared))
            names = fs.entries()
        else:
            require((DATA in names) != (STAGE in names))
            expected = prepared["system_identifier"]
            require(
                control(backend, STAGE if STAGE in names else DATA, initial=STAGE in names)
                == expected
            )
        if STAGE in names:
            backend.check()
            fs.move_directory(STAGE, DATA)
        first = True
    if not first:
        require(control(backend, DATA, initial=False) == expected)
    for name, raw in backend.plan.files.items():
        backend.check()
        # A completed installation must retain its exact auth/config files.
        require(first or (fs.read(name) == raw and fs.read("." + name + ".pending") is None))
        fs.publish(name, raw)
    require(set(backend.plan.files) == CONFIGS)
    return expected, first, final


def control(backend, name, *, initial):
    backend.check()
    backend.fs.check_version(name)
    raw = backend.run_command(
        backend.tools.control, (str(Path(backend.plan.postgres_root) / name),), capture=True
    )
    backend.check()
    return _records.control(raw, initial=initial)


def finish(backend, system, oid, first):
    value = _records.make("cluster", backend.installation, backend.tools.target, system, oid)
    backend.check()
    if first:
        backend.fs.publish("cluster.json", _records.encode(value))
    for kind in ("prepared", "initialization"):
        backend.check()
        name = kind + ".json"
        raw = backend.fs.read(name)
        if raw is not None:
            record = _records.decode(raw, kind, backend.installation, backend.tools.target)
            if kind == "prepared":
                require(record["system_identifier"] == system)
            backend.fs.remove(name, raw)
    return value
