"""Explicit synthetic launcher; no real engine or configurable executable endpoint."""

import os
import subprocess
import sys
import threading
from pathlib import Path
from types import MappingProxyType
from weakref import WeakSet

from ..wire import StreamDecoder
from ..wire._codec import binding_copy
from ._errors import LocalResource, MacRuntimeError
from ._locks import SlotLease

MODES = frozenset(
    (
        "success",
        "review",
        "review2",
        "local_model",
        "wait",
        "ignore_term",
        "result_hang",
        "nonzero",
        "tail",
        "error",
        "stderr_flood",
        "early_exit",
        "prepared_missing",
        "prepared_extra",
    )
)
ENTRY = Path(__file__).with_name("_guardian_entry.py")
CHILD_ENTRY = Path(__file__).with_name("_child_entry.py")
MINIMAL_ENV = MappingProxyType({"LC_ALL": "C", "LANG": "C"})
_ISSUE = object()
_ISSUED = WeakSet()


class FixtureGuardian(LocalResource):
    def __new__(cls, key=None, *args):
        if key is not _ISSUE:
            raise TypeError("guardians are issued by the synthetic launcher")
        return super().__new__(cls)

    def __init__(self, key, process, fds):
        if key is not _ISSUE or self in _ISSUED:
            raise TypeError("guardian handles are issued once")
        self._process, self._fds, self._pid = process, dict(fds), os.getpid()
        self._mutex = threading.Lock()
        _ISSUED.add(self)

    def _check(self):
        if type(self) is not FixtureGuardian or self not in _ISSUED or self._pid != os.getpid():
            raise MacRuntimeError("invalid_handle")

    @property
    def process(self):
        self._check()
        return self._process

    def _fd(self, name):
        self._check()
        with self._mutex:
            if name not in self._fds:
                raise MacRuntimeError("invalid_handle")
            return self._fds[name]

    @property
    def control_fd(self):
        return self._fd("control")

    @property
    def request_fd(self):
        return self._fd("request")

    @property
    def events_fd(self):
        return self._fd("events")

    @property
    def status_fd(self):
        return self._fd("status")

    @property
    def armed_fd(self):
        return self._fd("armed")

    def _close(self, name):
        fd = self._fds.pop(name, None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                raise MacRuntimeError("runtime_unavailable") from None

    def close_control(self):
        self._check()
        with self._mutex:
            self._close("control")

    def close_request(self):
        self._check()
        with self._mutex:
            self._close("request")

    def close(self):
        self._check()
        with self._mutex:
            failed = False
            for name in tuple(self._fds):
                try:
                    self._close(name)
                except MacRuntimeError:
                    failed = True
            if failed:
                raise MacRuntimeError("runtime_unavailable")


def launch_fixture_guardian(slot, binding, *, deadline_ns, lease_ns, mode="success"):
    if (
        type(mode) is not str
        or mode not in MODES
        or type(deadline_ns) is not int
        or type(lease_ns) is not int
        or not 0 < lease_ns <= deadline_ns <= 2**63 - 1
    ):
        raise MacRuntimeError("validation_error")
    try:
        binding = binding_copy(binding)
        StreamDecoder(binding, lane="control")  # exact detached UUID binding validation
    except Exception:
        raise MacRuntimeError("validation_error") from None
    if type(slot) is not SlotLease:
        raise MacRuntimeError("invalid_handle")
    slot_fd = slot.fileno()
    owned, parent, child = set(), {}, {}
    try:
        for name in ("control", "request", "events", "status", "armed"):
            reader, writer = os.pipe()
            owned.update((reader, writer))
            parent[name], child[name] = (
                (writer, reader) if name in ("control", "request") else (reader, writer)
            )
            os.set_blocking(parent[name], False)
        args = [
            sys.executable,
            "-I",
            "-B",
            str(ENTRY),
            str(binding.run_id),
            str(binding.attempt_id),
            str(deadline_ns),
            str(lease_ns),
            mode,
            *(str(child[name]) for name in ("control", "request", "events", "status", "armed")),
            str(slot_fd),
        ]
        process = subprocess.Popen(
            args,
            shell=False,
            close_fds=True,
            pass_fds=(*child.values(), slot_fd),
            start_new_session=True,
            env=dict(MINIMAL_ENV),
            cwd=str(ENTRY.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for fd in child.values():
            owned.remove(fd)
            os.close(fd)
        result = FixtureGuardian(_ISSUE, process, parent)
        owned.clear()
        return result
    except Exception:
        raise MacRuntimeError("runtime_unavailable") from None
    finally:
        for fd in owned:
            try:
                os.close(fd)
            except OSError:
                pass
