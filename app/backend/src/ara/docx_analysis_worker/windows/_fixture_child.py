"""SYNTHETIC ONLY: opaque reply, deliberately not a real B1 model response."""

import base64
import ctypes as c
import hashlib
import time

from ..wire import encode_message


def run_fixture(api, binding, request, mode, emit, diagnostic_handle):
    if mode == "local_model":
        from ..native_model import run_native

        return run_native(request, emit)

    def send(kind, seq, **values):
        emit(encode_message(binding, kind=kind, seq=seq, values=values))

    send("ready", 0, execution_spec_sha256=request.values["execution_spec_sha256"])
    send("stage", 1, stage="loading_model")
    send("stage", 2, stage="analyzing")
    if mode in ("native_hang", "result_hang"):
        # PyDLL intentionally keeps this process's GIL; G is an independent process.
        native = c.PyDLL("kernel32.dll", winmode=0x800)
        native.Sleep.argtypes, native.Sleep.restype = [c.c_uint32], None
    if mode == "native_hang":
        native.Sleep(5000)
        return 76
    if mode == "wait":
        time.sleep(5)
        return 76
    if mode == "error":
        send("error", 3, code="adapter_error")
        return 76
    if mode == "diagnostic_flood":
        write = api.kernel.WriteFile
        # Synchronous handle uses the existing signature; NULL OVERLAPPED.
        raw, count = c.create_string_buffer(b"x" * 65537), c.c_uint32()
        offset = 0
        while offset < 65537:
            api.require(
                write(diagnostic_handle, c.byref(raw, offset), 65537 - offset, c.byref(count), None)
            )
            api.require(0 < count.value <= 65537 - offset)
            offset += count.value
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
            send("error", 3, code="adapter_error")
            return 76
    send(
        "result",
        3,
        reply_sha256=hashlib.sha256(reply).hexdigest(),
        reply_b64=base64.b64encode(reply).decode("ascii"),
    )
    if mode == "result_hang":
        native.Sleep(5000)
        return 76
    if mode == "tail":
        emit(b"!")
    if mode in ("exit_259", "exit_ntstatus"):
        exit_process = api.kernel.ExitProcess
        exit_process.argtypes, exit_process.restype = [c.c_uint32], None
        exit_process(259 if mode == "exit_259" else 0xC0000005)
    return 76 if mode == "nonzero" else 0
