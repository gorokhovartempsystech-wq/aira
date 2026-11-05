"""Detached host metadata; capability bytes are never represented in diagnostics."""

import json
from dataclasses import dataclass, field

_ERRORS = {
    "validation_error": (422, "Invalid host input"),
    "invalid_handle": (500, "Host belongs to another runtime"),
    "runtime_in_use": (409, "Application runtime is already owned"),
    "server_error": (503, "Local server failed"),
    "lifespan_error": (503, "Application lifecycle failed"),
    "startup_timeout": (503, "Application startup timed out"),
    "server_stopping": (503, "Application is stopping"),
    "local_busy": (503, "Application request capacity is busy"),
    "request_timeout": (408, "Application request timed out"),
    "request_too_large": (413, "Application request is too large"),
    "unsupported_media": (415, "Unsupported application request encoding"),
}


class HostError(Exception):
    def __init__(self, code):
        self.code = code if type(code) is str and code in _ERRORS else "server_error"
        self.status, self.message = _ERRORS[self.code]
        super().__init__(self.message)


def fail(code):
    raise HostError(code) from None


def require(condition, code="validation_error"):
    if not condition:
        fail(code)


@dataclass(frozen=True)
class HostView:
    phase: str
    error_code: str | None
    resources_pending: bool
    clean_shutdown: bool


@dataclass(frozen=True)
class LocalConnection:
    origin: str
    session_token: bytes = field(repr=False)


async def error_reply(send, error):
    data = json.dumps(
        {"code": error.code, "message": error.message}, separators=(",", ":")
    ).encode()
    await send(
        dict(
            type="http.response.start",
            status=error.status,
            headers=[
                (b"content-type", b"application/json"),
                (b"content-length", str(len(data)).encode()),
                (b"cache-control", b"no-store"),
                (b"x-content-type-options", b"nosniff"),
                (b"referrer-policy", b"no-referrer"),
            ],
        )
    )
    await send(dict(type="http.response.body", body=data))
