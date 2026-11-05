"""Complete requests before dispatch, with independent admission for user Stop."""

import re
from threading import BoundedSemaphore

import anyio

from ara.docx_package import DocxLimits

from ._models import HostError, error_reply, fail, require

BODY_TIMEOUT = 15.0
MAX_FRAMES = 32768


def maximum(scope):
    if scope["method"] == "GET" or scope["path"].endswith("/create"):
        return 0
    if scope["path"].endswith("/import"):
        return DocxLimits().max_archive_bytes
    if scope["path"].endswith("/commands"):
        return 8 * 1024 * 1024
    return 65536


async def collect(scope, receive):
    cap = maximum(scope)
    headers = {}
    for name, value in scope.get("headers", []):
        headers.setdefault(name.lower(), []).append(value)
    for name in (b"content-length", b"transfer-encoding", b"content-encoding"):
        require(len(headers.get(name, [])) <= 1)
    length = headers.get(b"content-length", [None])[0]
    transfer = headers.get(b"transfer-encoding", [None])[0]
    encoding = headers.get(b"content-encoding", [b"identity"])[0]
    require(encoding.strip().lower() == b"identity", "unsupported_media")
    if transfer is not None:
        require(length is None and transfer.strip().lower() == b"chunked")
    if length is not None:
        require(re.fullmatch(rb"[0-9]{1,19}", length) is not None)
        length = int(length)
        require(cap != 0 or length == 0)
        require(length <= cap, "request_too_large")
    data = bytearray()
    try:
        with anyio.fail_after(BODY_TIMEOUT):
            for _ in range(MAX_FRAMES):
                message = await receive()
                require(type(message) is dict and message.get("type") == "http.request")
                chunk, more = message.get("body", b""), message.get("more_body", False)
                require(type(chunk) is bytes and type(more) is bool)
                require(cap != 0 or not chunk)
                require(len(data) + len(chunk) <= cap, "request_too_large")
                data.extend(chunk)
                if not more:
                    require(length is None or length == len(data))
                    return bytes(data)
    except TimeoutError:
        fail("request_timeout")
    fail("validation_error")


class BodyEnvelope:
    def __init__(self, application, state):
        self.application, self.state = application, state
        self.ordinary, self.stop = BoundedSemaphore(2), BoundedSemaphore(1)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return
        stop = scope["method"] == "POST" and re.fullmatch(
            r"/docx-documents/[^/]+/analysis-requests/[^/]+/stop", scope["path"]
        )
        gate = self.stop if stop else self.ordinary
        if not gate.acquire(blocking=False):
            await error_reply(send, HostError("local_busy"))
            return
        try:
            try:
                data = await collect(scope, receive)
            except HostError as error:
                await error_reply(send, error)
                return
            consumed = False

            async def replay():
                nonlocal consumed, data
                if not consumed:
                    consumed = True
                    body, data = data, b""
                    return dict(type="http.request", body=body, more_body=False)
                return await receive()

            await self.application({**scope, "state": self.state.copy()}, replay, send)
        finally:
            gate.release()
