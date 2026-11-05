"""Exclusive private output, bounded copies and unchanged independent verification."""

import json
import os
from contextlib import contextmanager
from hashlib import sha256

from ara.desktop.installation import FileRecord, PackageError, parse_manifest, verify_installation
from ara.desktop.installation._files import CHUNK, Tree, _admit, _stamp
from ara.desktop.installation._manifest import EXECUTABLE, NAME

from ._inventory import scan
from ._models import BuildError, BuildReceipt, arguments, require


@contextmanager
def _errors(code):
    try:
        yield
    except BuildError:
        raise
    except Exception:
        raise BuildError(code) from None


def _manifest(options, records):
    indexed = {r.path: r for r in records}
    model = options["entrypoints"]["model_manifest"]
    body = dict(
        schema_version="aira-installation/1",
        product="aira",
        **options,
        files=[
            dict(path=r.path, bytes=r.size, sha256=r.sha256, executable=r.executable)
            for r in records
        ],
        model_manifest_sha256=indexed[model].sha256 if model in indexed else None,
    )
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    pin = sha256(raw).hexdigest()
    parsed = parse_manifest(raw, expected_sha256=pin, target=options["target"], allow_fixture=True)
    return raw, pin, parsed


def _destinations(source, destination):
    with _errors("validation_error"):
        real_source = source.resolve(strict=False)
        real_destination = destination.parent.resolve(strict=False) / destination.name
        require(
            not real_source.is_relative_to(real_destination)
            and not real_destination.is_relative_to(real_source)
        )
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        raise BuildError("destination_unavailable") from None
    else:
        raise BuildError("destination_exists") from None
    with _errors("destination_unavailable"):
        _admit(destination.parent.lstat(), directory=True)


@contextmanager
def _output(path, executable=False):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    mode = 0o755 if executable else 0o644
    with _errors("build_failed"):
        fd = os.open(path, flags, mode)
        try:
            if os.name == "posix":
                os.fchmod(fd, mode)
            yield fd
            os.fsync(fd)
        finally:
            os.close(fd)


def _write(fd, data):
    block = memoryview(data)
    while block:
        written = os.write(fd, block[:CHUNK])
        require(type(written) is int and 0 < written <= min(len(block), CHUNK), "build_failed")
        block = block[written:]


def _copy(tree, destination, record, inventory):
    digest, count = sha256(), 0
    with _errors("source_changed"), tree.file(record.path, inventory.stamps) as (source_fd, info):
        require(info.st_size == record.size, "source_changed")
        with _output(destination / record.path, record.executable) as output_fd:
            while count <= record.size:
                cap = min(CHUNK, record.size + 1 - count)
                with _errors("source_changed"):
                    data = os.read(source_fd, cap)
                require(type(data) is bytes and len(data) <= cap, "source_changed")
                if not data:
                    break
                count += len(data)
                require(count <= record.size, "source_changed")
                _write(output_fd, data)
                digest.update(data)
            require(
                count == record.size and _stamp(os.fstat(source_fd)) == _stamp(info),
                "source_changed",
            )
    return FileRecord(record.path, count, digest.hexdigest(), record.executable)


def _unchanged(tree, inventory):
    with _errors("source_changed"):
        require(scan(tree) == inventory, "source_changed")


def _assemble(tree, destination, options, extras):
    with _errors("source_invalid"):
        inventory = scan(tree)
        require(all(path in inventory.sizes for path in extras), "source_invalid")
        executable = {options["entrypoints"][r] for r in EXECUTABLE} | set(extras)
        records = tuple(
            FileRecord(p, size, "0" * 64, p in executable)
            for p, size in sorted(inventory.sizes.items())
        )
        _manifest(options, records)
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError:
        raise BuildError("destination_exists") from None
    except OSError:
        raise BuildError("destination_unavailable") from None
    with _errors("build_failed"):
        for path in inventory.directories:
            (destination / path).mkdir(mode=0o700)
        copied = tuple(_copy(tree, destination, record, inventory) for record in records)
        _unchanged(tree, inventory)
        raw, pin, _ = _manifest(options, copied)
        with _output(destination / NAME) as fd:
            _write(fd, raw)
        verified = verify_installation(
            destination,
            expected_sha256=pin,
            target=options["target"],
            allow_fixture=options["kind"] == "fixture",
        )
        _unchanged(tree, inventory)
        return BuildReceipt(verified, raw, pin)


def build_payload(
    source_root, destination, *, version, target, kind, entrypoints, extra_executables=()
):
    """Build only in a fresh directory; failure keeps partial output and yields no receipt."""
    options, extras = arguments(
        source_root, destination, version, target, kind, entrypoints, extra_executables
    )
    _destinations(source_root, destination)
    try:
        with Tree(source_root).opened() as tree:
            return _assemble(tree, destination, options, extras)
    except BuildError:
        raise
    except PackageError:
        raise BuildError("source_invalid") from None
    except OSError:
        raise BuildError("source_unavailable") from None
    except Exception:
        raise BuildError() from None
