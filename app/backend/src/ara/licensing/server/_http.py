"""Bounded HTTPS-only license API; no administrative endpoints or automatic setup."""

import re

import anyio
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

from ara import licensing as core
from ara.licensing._models import MAX_BODY

from ._models import ServerError, fail, require, validate_runtime
from ._storage import process_request

BODY_TIMEOUT = 5.0


class _NoStore:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def sending(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"
                ]
                message = dict(message, headers=[*headers, (b"cache-control", b"no-store")])
            await send(message)

        await self.app(scope, receive, sending)


async def _body(request):
    require(not request.scope.get("query_string"))
    media = request.headers.getlist("content-type")
    require(
        len(media) == 1
        and media[0].lower().replace(" ", "")
        in ("application/json", "application/json;charset=utf-8"),
        "unsupported_media",
    )
    lengths = request.headers.getlist("content-length")
    expected = None
    if lengths:
        require(len(lengths) == 1 and re.fullmatch(r"[0-9]{1,20}", lengths[0]) is not None)
        expected = int(lengths[0])
        require(expected <= MAX_BODY, "request_too_large")
    data = bytearray()
    frames = 0
    try:
        with anyio.fail_after(BODY_TIMEOUT):
            async for chunk in request.stream():
                frames += 1
                require(frames <= 128 and len(data) + len(chunk) <= MAX_BODY, "request_too_large")
                data.extend(chunk)
    except TimeoutError:
        fail("request_timeout")
    require(expected is None or expected == len(data))
    return bytes(data)


def _schema(operation):
    def record(properties):
        return dict(
            type="object",
            properties=properties,
            required=list(properties),
            additionalProperties=False,
        )

    uid = dict(type="string", format="uuid", description="Canonical nonzero UUID")
    device = dict(type="string", pattern="^dv1-[0-9a-f]{64}$")
    nonce = dict(type="string", pattern="^[0-9a-f]{64}$")
    time = dict(
        type="string", pattern="^(0|[1-9][0-9]{0,14})$", description="UTC epoch milliseconds"
    )
    inputs = dict(
        schema_version=dict(const="aira-license-request/1"),
        operation=dict(const=operation),
        device_id=device,
        nonce=nonce,
    )
    inputs.update(
        dict(license_key=dict(type="string", maxLength=128))
        if operation == "activate"
        else dict(license_id=uid)
    )
    grant = record(
        dict(
            schema_version=dict(const="aira-license-grant/1"),
            operation=dict(const=operation),
            license_id=uid,
            device_id=device,
            nonce=nonce,
            activated_at_ms=time,
            checked_at_ms=time,
            expires_at_ms=time,
        )
    )
    return dict(
        requestBody=dict(required=True, content={"application/json": dict(schema=record(inputs))}),
        responses={
            "200": dict(
                description="Confirmed fixed-term entitlement for this nonce",
                content={"application/json": dict(schema=grant)},
            ),
            **{
                str(status): dict(description="Safe license error; no-store")
                for status in (400, 403, 408, 413, 415, 422, 500, 503)
            },
        },
    )


def create_license_app(runtime):
    validate_runtime(runtime)
    app = FastAPI(title="AIRA License Server", docs_url=None, redoc_url=None, openapi_url=None)
    admission = anyio.CapacityLimiter(4)
    workers = anyio.CapacityLimiter(4)

    async def execute(request, operation):
        acquired = False
        try:
            try:
                admission.acquire_nowait()
            except anyio.WouldBlock:
                fail("license_busy")
            acquired = True
            require(request.scope.get("scheme") == "https", "https_required")
            command = core.decode_request(await _body(request))
            require(command.operation == operation)
            with anyio.CancelScope(shield=True):
                data = await anyio.to_thread.run_sync(
                    process_request, runtime, command, limiter=workers
                )
            return Response(data, media_type="application/json")
        except (core.LicenseError, ServerError) as error:
            return JSONResponse(
                dict(code=error.code, message=error.message), status_code=error.status
            )
        except Exception:
            error = ServerError("license_storage_error")
            return JSONResponse(
                dict(code=error.code, message=error.message), status_code=error.status
            )
        finally:
            if acquired:
                admission.release()

    @app.post("/license/v1/activate", openapi_extra=_schema("activate"))
    async def activate(request: Request):
        return await execute(request, "activate")

    @app.post("/license/v1/check", openapi_extra=_schema("check"))
    async def check(request: Request):
        return await execute(request, "check")

    app.add_middleware(_NoStore)
    return app
