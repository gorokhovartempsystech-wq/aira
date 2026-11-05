"""Process-local exclusive app/client ownership; failed cleanup retains its claim."""

import os
from threading import Lock

from ._models import require

_PID = os.getpid()
_LOCK = Lock()
_OWNERS = {}


def claim(owner, application, client):
    require(os.getpid() == _PID, "invalid_handle")
    keys = (("app", id(application)), ("client", id(client)))
    with _LOCK:
        require(all(key not in _OWNERS or _OWNERS[key] is owner for key in keys), "runtime_in_use")
        for key in keys:
            _OWNERS[key] = owner


def release(owner):
    require(os.getpid() == _PID, "invalid_handle")
    with _LOCK:
        for key in tuple(_OWNERS):
            if _OWNERS[key] is owner:
                del _OWNERS[key]
