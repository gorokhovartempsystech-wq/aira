"""One strong composition owner; ambiguous creation is never inferred closed."""

import os
import threading

from ._models import require

_PID = os.getpid()
_LOCK = threading.Lock()
_OWNER = None


def claim(owner):
    global _OWNER
    require(os.getpid() == _PID, "invalid_handle")
    with _LOCK:
        require(_OWNER is None, "desktop_busy")
        _OWNER = owner


def release(owner):
    global _OWNER
    require(os.getpid() == _PID, "invalid_handle")
    with _LOCK:
        if _OWNER is owner:
            _OWNER = None
