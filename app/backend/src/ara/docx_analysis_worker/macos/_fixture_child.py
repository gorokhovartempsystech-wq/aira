"""SYNTHETIC FIXTURE ONLY. Its opaque reply is deliberately not a real B1 analysis."""

import base64
import hashlib
import os
import signal
import sys
import time

from ..wire import encode_message


def run_fixture(binding, request, mode):
    if mode == "local_model":
        from ..native_model import run_native

        def write(raw):
            while raw:
                count = os.write(1, raw)
                if count <= 0:
                    raise OSError()
                raw = raw[count:]

        return run_native(request, write)
    native_hang = mode in ("ignore_term", "result_hang")
    library = None
    if native_hang:
        import ctypes

        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        sys.setswitchinterval(10.0)
        library = ctypes.PyDLL(None)
        library.write.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t]
        library.write.restype = ctypes.c_ssize_t
        library.sleep.argtypes = [ctypes.c_uint]
        library.sleep.restype = ctypes.c_uint

    def emit(kind, seq, **values):
        raw = encode_message(binding, kind=kind, seq=seq, values=values)
        while raw:
            count = library.write(1, raw, len(raw)) if library else os.write(1, raw)
            if count <= 0:
                raise OSError()
            raw = raw[count:]

    emit("ready", 0, execution_spec_sha256=request.values["execution_spec_sha256"])
    emit("stage", 1, stage="loading_model")
    emit("stage", 2, stage="analyzing")
    if mode == "ignore_term":
        library.sleep(5)
        return 76
    if mode == "wait":
        time.sleep(5)
        return 76
    if mode == "error":
        emit("error", 3, code="adapter_error")
        return 76
    if mode == "stderr_flood":
        raw = b"x" * 65537
        while raw:
            raw = raw[os.write(2, raw) :]
        return 0
    reply = b"fixture-response"
    if mode in ("review", "review2"):
        from ..review_fixture import ReviewFixtureError

        if mode == "review2":
            from ..structured_fixture import reply_for
        else:
            from ..review_fixture import reply_for

        try:
            reply = reply_for(request)
        except ReviewFixtureError:
            emit("error", 3, code="adapter_error")
            return 76
    emit(
        "result",
        3,
        reply_sha256=hashlib.sha256(reply).hexdigest(),
        reply_b64=base64.b64encode(reply).decode(),
    )
    if mode == "result_hang":
        library.sleep(5)
        return 76
    if mode == "tail":
        os.write(1, b"!")
    return 76 if mode == "nonzero" else 0
