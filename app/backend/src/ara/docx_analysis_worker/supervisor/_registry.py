"""Strong process-local ownership; changing root or UUID cannot replace live work."""

import os
from threading import Lock

from ._runtime_models import SupervisorError

_LOCK = Lock()
_LIVE = {}


def acquire(value):
    with _LOCK:
        previous = _LIVE.get(os.getpid())
        if previous is not None and previous is not value:
            if previous._finished.is_set() and all(not t.is_alive() for t in previous._threads()):
                del _LIVE[os.getpid()]
            else:
                raise SupervisorError("busy")
        _LIVE[os.getpid()] = value


def release(value):
    with _LOCK:
        if _LIVE.get(os.getpid()) is value:
            del _LIVE[os.getpid()]
