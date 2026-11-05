"""Explicit native IO for a trusted Python host; no picker or network access."""

import hashlib
import os
import stat
import tempfile
from pathlib import Path
from threading import Lock

from .state import Observation

LIMIT = 32 * 1024 * 1024


class NativeFileError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fail(code):
    raise NativeFileError(code) from None


def destination(raw):
    """Canonicalize a trusted native selection before preparing an SQL intent."""
    try:
        p = Path(raw)
        if not p.is_absolute() or p.suffix.lower() != ".docx" or "\0" in str(p):
            fail("invalid_file_path")
        return str(p.parent.resolve(strict=True) / p.name)
    except NativeFileError:
        raise
    except Exception:
        fail("file_io_error")


def identity(s):
    return "native-v1:" + ":".join(
        str(x)
        for x in (
            s.st_dev,
            s.st_ino,
            s.st_size,
            s.st_mtime_ns,
            s.st_ctime_ns,
            s.st_mode,
            s.st_nlink,
        )
    )


def _read(path):
    first = os.lstat(path)
    if not stat.S_ISREG(first.st_mode) or first.st_nlink != 1 or first.st_size > LIMIT:
        fail("unsafe_file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    try:
        before = os.fstat(fd)
        if identity(before) != identity(first) or before.st_nlink != 1:
            fail("file_changed")
        chunks, length = [], 0
        while length <= LIMIT:
            chunk = os.read(fd, min(65536, LIMIT + 1 - length))
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
        if length > LIMIT:
            fail("file_too_large")
        after = os.fstat(fd)
        last = os.lstat(path)
        if (
            length != before.st_size
            or identity(before) != identity(after)
            or identity(after) != identity(last)
        ):
            fail("file_changed")
        data = b"".join(chunks)
        return (
            Observation(
                path=path, identity=identity(after), sha256=hashlib.sha256(data).hexdigest()
            ),
            data,
            stat.S_IMODE(after.st_mode) & 0o777,
        )
    finally:
        os.close(fd)


class NativeFiles:
    """One host instance, blocking IO intended for a worker thread."""

    def __init__(self):
        self._lock = Lock()

    def selected(self, path):
        try:
            observation, data, _ = _read(destination(path))
            return observation, data
        except NativeFileError:
            raise
        except Exception:
            fail("file_read_failed")

    def observe(self, path):
        canonical = destination(path)
        try:
            observation, _, _ = _read(canonical)
            return observation
        except FileNotFoundError:
            # Recheck name absence: a disappearance during read is a conflict.
            if os.path.lexists(canonical):
                fail("file_changed")
            return None
        except NativeFileError:
            raise
        except Exception:
            fail("file_read_failed")

    def write(self, path, data, expected):
        if type(data) is not bytes or not 0 < len(data) <= LIMIT:
            fail("invalid_file_payload")
        if not self._lock.acquire(blocking=False):
            fail("file_busy")
        temporary, fd, published = None, None, False
        try:
            canonical = destination(path)
            current = self.observe(canonical)
            if current != expected:
                fail("file_changed")
            mode = 0o600
            if expected is not None:
                _, _, mode = _read(canonical)
            fd, temporary = tempfile.mkstemp(
                prefix=".aira-save-", suffix=".tmp", dir=Path(canonical).parent
            )
            view = memoryview(data)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    fail("file_write_failed")
                view = view[count:]
            if os.name == "nt":
                os.chmod(temporary, mode)
            else:
                os.fchmod(fd, mode)
            os.fsync(fd)
            closing_fd, fd = fd, None
            os.close(closing_fd)
            if self.observe(canonical) != expected:
                fail("file_changed")
            if expected is None:
                os.link(temporary, canonical)  # atomic no-replace, including late arrival
                published = True
                os.unlink(temporary)
            else:
                os.replace(temporary, canonical)
                published = True
            temporary = None
            if os.name != "nt":
                directory = os.open(str(Path(canonical).parent), os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            observed = self.observe(canonical)
            if observed is None or observed.sha256 != hashlib.sha256(data).hexdigest():
                fail("file_write_uncertain")
            return observed
        except Exception as error:
            if published:
                fail("file_write_uncertain")
            if isinstance(error, NativeFileError):
                raise error from None
            fail("file_write_failed")
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            self._lock.release()
