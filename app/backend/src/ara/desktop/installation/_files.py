"""Read-only streaming preflight of a trusted, quiescent installation subtree."""

import os
import stat
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path

from ._manifest import MAX_MANIFEST, NAME, arguments, parse_manifest
from ._models import PackageError, VerifiedInstallation, require

CHUNK = 1024 * 1024


def _stamp(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        getattr(info, "st_file_attributes", 0),
    )


def _admit(info, *, directory=False):
    require(not getattr(info, "st_file_attributes", 0) & 0x400)
    require(
        stat.S_ISDIR(info.st_mode)
        if directory
        else stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    )


class Tree:
    def __init__(self, root):
        self.root = root
        self.fd = None
        self.initial = None

    @contextmanager
    def opened(self):
        self.initial = self.root.lstat()
        _admit(self.initial, directory=True)
        if os.name == "posix":
            self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if self.fd is not None:
                require(_stamp(os.fstat(self.fd)) == _stamp(self.initial))
            yield self
        finally:
            if self.fd is not None:
                fd, self.fd = self.fd, None
                os.close(fd)

    def path(self, parent, name):
        return self.root.joinpath(*parent.split("/"), name) if parent else self.root / name

    def info(self, parent, name, fd):
        return os.stat(
            name if fd is not None else self.path(parent, name), dir_fd=fd, follow_symlinks=False
        )

    @contextmanager
    def directory(self, parent, name, fd, info):
        _admit(info, directory=True)
        if fd is None:
            yield None
            return
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            opened = os.fstat(child)
            _admit(opened, directory=True)
            require(_stamp(opened) == _stamp(info))
            yield child
        finally:
            os.close(child)

    def inventory(self, manifest):
        children = {"": set()}
        wanted = {NAME: None, **{r.path: r for r in manifest.files}}
        for path in wanted:
            parts = path.split("/")
            for i, name in enumerate(parts):
                parent = "/".join(parts[:i])
                children.setdefault(parent, set()).add(name)
        found = {"": _stamp(self.root.lstat())}
        require(found[""] == _stamp(self.initial))

        def walk(parent, fd):
            seen = set()
            with os.scandir(
                fd if fd is not None else self.root.joinpath(*parent.split("/"))
            ) as entries:
                for entry in entries:
                    name = entry.name
                    require(name in children[parent] and name not in seen)
                    seen.add(name)
                    path = "/".join((parent, name)) if parent else name
                    info = self.info(parent, name, fd)
                    found[path] = _stamp(info)
                    if path in children:
                        with self.directory(parent, name, fd, info) as child:
                            walk(path, child)
                    else:
                        _admit(info)
                        record = wanted[path]
                        if (
                            record is not None
                            and record.executable
                            and manifest.target.startswith("macos-")
                        ):
                            if os.name == "posix":
                                require(info.st_mode & 0o111 != 0)
            require(seen == children[parent], "package_unavailable")

        walk("", self.fd)
        return found

    @contextmanager
    def file(self, path, snapshots=None):
        parts = path.split("/")
        parent, fd = "", self.fd
        with ExitStack() as stack:
            for name in parts[:-1]:
                info = self.info(parent, name, fd)
                full = "/".join((parent, name)) if parent else name
                if snapshots is not None:
                    require(_stamp(info) == snapshots[full])
                fd = stack.enter_context(self.directory(parent, name, fd, info))
                parent = full
            info = self.info(parent, parts[-1], fd)
            _admit(info)
            if snapshots is not None:
                require(_stamp(info) == snapshots[path])
            flags = (
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0)
            )
            file_fd = os.open(
                parts[-1] if fd is not None else self.path(parent, parts[-1]), flags, dir_fd=fd
            )
            try:
                opened = os.fstat(file_fd)
                _admit(opened)
                require(_stamp(opened) == _stamp(info))
                yield file_fd, info
            finally:
                os.close(file_fd)

    def read(self, path, *, snapshots=None, record=None):
        with self.file(path, snapshots) as (fd, info):
            cap = MAX_MANIFEST if record is None else record.size
            if record is None:
                require(0 < info.st_size <= cap)
            else:
                require(info.st_size == cap, "package_mismatch")
            count, hasher, blocks = 0, sha256(), []
            while count <= cap:
                data = os.read(fd, min(CHUNK, cap + 1 - count))
                if not data:
                    break
                count += len(data)
                hasher.update(data)
                if record is None:
                    blocks.append(data)
            # Check observations before content comparison to distinguish a mutation.
            require(_stamp(os.fstat(fd)) == _stamp(info))
            require(count == info.st_size, "package_mismatch")
            if record is not None:
                require(hasher.hexdigest() == record.sha256, "package_mismatch")
            return b"".join(blocks), _stamp(info)


def verify_installation(root, *, expected_sha256, target, allow_fixture=False):
    arguments(expected_sha256, target, allow_fixture)
    require(
        isinstance(root, Path) and root.is_absolute() and ".." not in root.parts, "validation_error"
    )
    try:
        with Tree(root).opened() as tree:
            raw, original = tree.read(NAME)
            manifest = parse_manifest(
                raw, expected_sha256=expected_sha256, target=target, allow_fixture=allow_fixture
            )
            inventory = tree.inventory(manifest)
            require(inventory[NAME] == original)
            for record in manifest.files:
                tree.read(record.path, snapshots=inventory, record=record)
            require(tree.inventory(manifest) == inventory)
            return VerifiedInstallation(Path(root), manifest)
    except PackageError:
        raise
    except OSError:
        raise PackageError("package_unavailable") from None
    except Exception:
        raise PackageError() from None
