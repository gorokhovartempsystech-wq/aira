"""Verified startup updates via WinSparkle 0.9.4, before opening any document.

The DLL verifies Ed25519 signatures. Never invoke an installer ourselves or
continue startup while an updater still owns a download/install operation.
"""

import base64
import ctypes
import json
import threading
from pathlib import Path
from urllib.parse import urlsplit


def startup_update(launcher: Path, version: str, *, loader=None, wait_seconds=3600):
    """Return True only when the updater started installation; caller must exit.

    No update, cancellation, missing network and invalid signatures return False.
    Cleanup joins the updater before the backend may start. Native calls are
    cdecl; keep callbacks alive until cleanup has joined all native threads.
    """
    config = json.loads((launcher / "release-config.json").read_text(encoding="utf-8"))
    origin = urlsplit(config["origin"])
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username
        or origin.query
        or origin.fragment
    ):
        raise ValueError("invalid update origin")
    key = config["public_key"].encode("ascii")
    if len(base64.b64decode(key, validate=True)) != 32:
        raise ValueError("invalid update public key")
    dll = (loader or ctypes.CDLL)(str((launcher / "WinSparkle.dll").resolve()))
    done = threading.Event()
    installing = threading.Event()
    callback = ctypes.CFUNCTYPE(None)
    can_shutdown = ctypes.CFUNCTYPE(ctypes.c_int)
    callbacks = []

    def bind(name, types, result=None):
        func = getattr(dll, "win_sparkle_" + name)
        func.argtypes = types
        func.restype = result
        return func

    def finished_install():
        installing.set()
        done.set()

    bind("set_app_details", [ctypes.c_wchar_p] * 3)("AIRA Team", "AIRA", version)
    bind("set_appcast_url", [ctypes.c_char_p])(
        (config["origin"].rstrip("/") + "/updates/windows-x64.xml").encode("ascii")
    )
    if bind("set_eddsa_public_key", [ctypes.c_char_p], ctypes.c_int)(key) != 1:
        raise ValueError("WinSparkle rejected verification key")
    # One bounded check at startup, not another timer while editing.
    bind("set_automatic_check_for_updates", [ctypes.c_int])(0)
    for name in ("error", "did_not_find_update", "update_cancelled", "update_dismissed"):
        cb = callback(done.set)
        callbacks.append(cb)
        bind("set_" + name + "_callback", [callback])(cb)
    cb = can_shutdown(lambda: 1)  # No backend, database or editor has been opened yet.
    callbacks.append(cb)
    bind("set_can_shutdown_callback", [can_shutdown])(cb)
    cb = callback(finished_install)
    callbacks.append(cb)
    bind("set_shutdown_request_callback", [callback])(cb)
    cleanup = bind("cleanup", [])
    try:
        bind("init", [])()
        bind("check_update_with_ui_and_install", [])()
        done.wait(wait_seconds)
    finally:
        cleanup()
    return installing.is_set()
