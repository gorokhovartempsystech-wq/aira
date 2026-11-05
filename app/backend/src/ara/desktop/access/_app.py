"""An opt-in outer boundary; bootstrap retains ownership of all service lifetimes."""

import os
import secrets
import threading

from ara.licensing.client import ClientError, LicenseClient

from . import _http, _policy
from ._models import AccessError, fail, require


def new_session_token():
    return secrets.token_bytes(32)


class LicensedApplication:
    def __init__(self, application, license_client, *, origin, session_token):
        require(callable(application) and type(license_client) is LicenseClient, "validation_error")
        require(type(session_token) is bytes and len(session_token) == 32, "validation_error")
        self._port = _policy.checked_origin(origin)
        self._origin, self._token = origin, session_token
        self._application, self._license = application, license_client
        self._pid = os.getpid()
        self._body_slots = threading.BoundedSemaphore(4)
        self._ever_verified = False

    def _owner(self):
        require(hasattr(self, "_pid") and self._pid == os.getpid(), "invalid_handle")

    def __copy__(self):
        fail("invalid_handle")

    def __deepcopy__(self, memo):
        fail("invalid_handle")

    def __reduce_ex__(self, protocol):
        fail("invalid_handle")

    def _observe(self):
        value = self._license.view()
        if value.phase == "active":
            try:
                self._license.require_active()
            except ClientError:
                value = self._license.view()
            else:
                self._ever_verified = True
        return value

    def _admit(self, kind):
        try:
            self._license.require_active()
        except ClientError:
            state = self._license.view()
            if kind == "preserve" and self._ever_verified and state.phase != "closed":
                return
            raise
        else:
            self._ever_verified = True

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind != "http":
            self._owner()
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            require(kind == "lifespan", "validation_error")
            await self._application(scope, receive, send)
            return
        started = False

        async def guarded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                require(not started, "local_error")
                message = {**message, "headers": _http.response_headers(message.get("headers", []))}
                started = True
            await send(message)

        try:
            self._owner()
            headers = _policy.local_request(
                scope, origin=self._origin, port=self._port, token=self._token
            )
            operation = _policy.classify(scope)
            if operation in {"status", "activate", "verify"}:
                status, body = await _http.license_request(self, operation, scope, receive, headers)
                await _http.reply(guarded_send, status, body)
                return
            self._admit(operation)
            inner_scope = {
                **scope,
                "headers": [
                    (name, value)
                    for name, value in scope["headers"]
                    if name.lower() != b"x-aira-session"
                ],
            }
            await self._application(inner_scope, receive, guarded_send)
        except Exception as error:
            if started:
                fail("local_error")
            if not isinstance(error, (AccessError, ClientError)):
                error = AccessError("local_error")
            await _http.reply(send, error.status, {"code": error.code, "message": error.message})
