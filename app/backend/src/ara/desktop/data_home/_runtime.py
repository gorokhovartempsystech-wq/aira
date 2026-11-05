"""One retained application-data owner, separate from the analysis worker owner."""

import os
import sys
import threading
from dataclasses import replace
from pathlib import Path

from ._identity import prepare
from ._models import CHILDREN, HomeError, HomeView, require

_PID = os.getpid()
_LOCK = threading.Lock()
_RECORDS = {}
_ORPHANS = []
_KEY = object()


def _origin():
    require(os.getpid() == _PID, "invalid_handle")


def default_root():
    try:
        if sys.platform == "darwin":
            import pwd

            base = Path(pwd.getpwuid(os.geteuid()).pw_dir)
            require(base.is_absolute(), "home_unavailable")
            return base / "Library" / "Application Support" / "AIRA"
        if sys.platform == "win32":
            from ._windows import known_folder

            return Path(known_folder()) / "AIRA"
        raise HomeError("unsupported_platform")
    except HomeError:
        raise
    except Exception:
        raise HomeError() from None


def _filesystem(root):
    if sys.platform == "darwin":
        from ._posix import Filesystem
    elif sys.platform == "win32":
        from ._windows import Filesystem
    else:
        raise HomeError("unsupported_platform")
    return Filesystem(root)


class Record:
    def __init__(self, filesystem):
        self.filesystem = filesystem
        self.owner = self.home = None
        self.uncertain_owner = False

    def cleanup(self):
        if self.uncertain_owner:
            return False
        try:
            if self.owner is not None:
                self.owner.close()
                self.owner = None
            self.filesystem.close()
            return True
        except BaseException:
            return False


def _release(record):
    with _LOCK:
        if _RECORDS.get(record.filesystem.key) is record:
            del _RECORDS[record.filesystem.key]


class DataHome:
    def __new__(cls, key=None, *args):
        if key is not _KEY:
            raise TypeError("Data homes are issued by open_home")
        return super().__new__(cls)

    def __init__(self, key, record, identity):
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._record, self._identity = record, identity
        self._phase, self._error = "open", None

    def __repr__(self):
        return "<DataHome>"

    def _check(self):
        require(getattr(self, "_pid", None) == os.getpid(), "invalid_handle")
        require(type(self) is DataHome and self._record.home is self, "invalid_handle")

    def __copy__(self):
        raise HomeError("invalid_handle")

    def __deepcopy__(self, memo):
        raise HomeError("invalid_handle")

    def __reduce_ex__(self, protocol):
        raise HomeError("invalid_handle")

    def identity(self):
        self._check()
        with self._lock:
            require(self._phase == "open", "invalid_handle")
            return replace(self._identity)

    def path(self, name):
        self._check()
        require(type(name) is str and name in ("root", *CHILDREN), "validation_error")
        with self._lock:
            require(self._phase == "open", "invalid_handle")
            root = self._record.filesystem.root
            return Path(root) if name == "root" else root / name

    def view(self):
        self._check()
        with self._lock:
            return HomeView(self._phase, self._error, self._phase != "closed")

    def close(self):
        self._check()
        with self._lock:
            if self._phase == "closed":
                return True
            if self._phase in {"closing", "failed"}:
                return False
            self._phase = "closing"
        cleaned = self._record.cleanup()
        if cleaned:
            _release(self._record)
        with self._lock:
            self._phase = "closed" if cleaned else "failed"
            self._error = None if cleaned else "home_unavailable"
        return cleaned


def open_home(root=None):
    _origin()
    root = default_root() if root is None else root
    require(
        isinstance(root, Path)
        and root.is_absolute()
        and ".." not in root.parts
        and bool(root.name)
        and "\x00" not in str(root),
        "validation_error",
    )
    filesystem = _filesystem(Path(root))
    record = Record(filesystem)
    claimed = False
    try:
        key = filesystem.open()
        with _LOCK:
            require(key not in _RECORDS, "home_busy")
            _RECORDS[key] = record
            claimed = True
        try:
            record.owner = filesystem.acquire_owner()
        except BaseException as error:
            if getattr(error, "code", None) == "runtime_busy":
                raise HomeError("home_busy") from None
            # An opaque native acquisition failure can include an unconfirmed close.
            # Keep our directory pins and process claim until this process exits.
            record.uncertain_owner = True
            raise HomeError() from None
        identity = prepare(filesystem)
        filesystem.recheck()
        home = DataHome(_KEY, record, identity)
        record.home = home
        return home
    except BaseException as error:
        cleaned = record.cleanup()
        if cleaned and claimed:
            _release(record)
        elif not cleaned and not claimed:
            with _LOCK:
                _ORPHANS.append(record)
        if isinstance(error, HomeError):
            raise
        raise HomeError() from None
