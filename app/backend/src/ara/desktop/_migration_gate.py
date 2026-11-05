"""Strong process-wide ownership of Alembic's global context, shared by schema jobs."""

import os
import threading

_LOCK = threading.Lock()
_OWNER = None
_PID = None


def claim(owner):
    global _OWNER, _PID
    pid = os.getpid()
    if _PID is not None and _PID != pid:
        return False
    with _LOCK:
        if _OWNER is not None:
            return False
        _PID, _OWNER = pid, owner
        return True


def release(owner):
    global _OWNER
    if _PID != os.getpid():
        return
    with _LOCK:
        if _OWNER is owner:
            _OWNER = None
