"""HTTPS-only panel with bounded requests, opaque sessions and same-origin CSRF."""

import hmac
import json
import threading
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, Request
from starlette.responses import FileResponse, JSONResponse

from ara.licensing import LicenseError
from ara.licensing.server import ServerError

from .security import AdminError, need
from .service import SESSION_MS

PREFIX = "/license-admin"
COOKIE = "__Host-aira_admin"
HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}


def response(data, status=200):
    return JSONResponse(data, status_code=status, headers=HEADERS)


async def body(request):
    need(
        request.headers.get("content-type", "").split(";")[0].strip() == "application/json",
        415,
        "json_required",
    )
    data = bytearray()
    try:
        with anyio.fail_after(5):
            async for chunk in request.stream():
                data.extend(chunk)
                need(len(data) <= 4096, 413, "request_too_large")
    except TimeoutError:
        raise AdminError(408, "request_timeout") from None

    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result)
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise AdminError(422, "invalid_input") from None
    need(type(value) is dict)
    return value


def create_app(service):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    slots = threading.BoundedSemaphore(4)
    assets = Path(__file__).with_name("static")

    @app.middleware("http")
    async def secure(request, call_next):
        if (
            request.url.scheme != "https"
            or str(request.base_url).rstrip("/") != service.settings.origin
        ):
            return response({"code": "https_required"}, 400)
        try:
            result = await call_next(request)
        except Exception:
            return response({"code": "service_unavailable"}, 503)
        result.headers.update(HEADERS)
        return result

    @app.get(PREFIX + "/", include_in_schema=False)
    def index():
        return FileResponse(assets / "index.html", media_type="text/html", headers=HEADERS)

    @app.get(PREFIX + "/admin.js", include_in_schema=False)
    def script():
        return FileResponse(assets / "admin.js", media_type="text/javascript", headers=HEADERS)

    @app.get(PREFIX + "/admin.css", include_in_schema=False)
    def style():
        return FileResponse(assets / "admin.css", media_type="text/css", headers=HEADERS)

    @app.api_route(PREFIX + "/api/{action}", methods=["GET", "POST"], include_in_schema=False)
    async def api(action, request: Request):
        acquired = False
        try:
            need(action in {"login", "state", "issue", "disable", "logout"}, 404, "not_found")
            need(
                request.method == ("GET" if action == "state" else "POST"),
                405,
                "method_not_allowed",
            )
            need(request.headers.get("x-aira-admin-request") == "1", 403, "origin_required")
            origin = request.headers.get("origin")
            referer = urlsplit(request.headers.get("referer", ""))
            need(
                origin == service.settings.origin
                or (
                    request.method == "GET"
                    and origin is None
                    and referer.scheme + "://" + referer.netloc == service.settings.origin
                    and referer.path.startswith(PREFIX + "/")
                ),
                403,
                "origin_required",
            )
            cookie_values = [
                c
                for c in request.headers.get("cookie", "").split(";")
                if c.strip().startswith(COOKIE + "=")
            ]
            need(len(cookie_values) <= 1, 401, "sign_in_required")
            token = request.cookies.get(COOKIE)
            if action not in {"login", "state"}:
                csrf = request.headers.get("x-aira-admin-csrf", "")
                need(
                    type(token) is str
                    and len(token) == 64
                    and hmac.compare_digest(csrf, service.csrf(token)),
                    403,
                    "csrf_required",
                )
            acquired = slots.acquire(blocking=False)
            need(acquired, 429, "try_later")
            value = await body(request) if request.method == "POST" else {}
            if action == "login":
                need(set(value) == {"username", "password"})
                token = await anyio.to_thread.run_sync(
                    lambda: service.login(
                        value["username"],
                        value["password"],
                        request.client.host if request.client else "unknown",
                    )
                )
                result = response({"ok": True})
                result.set_cookie(
                    COOKIE,
                    token,
                    max_age=SESSION_MS // 1000,
                    secure=True,
                    httponly=True,
                    samesite="strict",
                    path="/",
                )
                return result
            if action == "state":
                raw = request.query_params.get("offset", "0")
                need(raw.isascii() and raw.isdigit() and len(raw) <= 7)
                return response(
                    await anyio.to_thread.run_sync(lambda: service.state(token, offset=int(raw)))
                )
            if action == "issue":
                need(set(value) == {"identifier", "key", "days", "label"})
                return response(
                    await anyio.to_thread.run_sync(lambda: service.issue(token, **value))
                )
            if action == "disable":
                need(set(value) == {"identifier"})
                await anyio.to_thread.run_sync(lambda: service.disable(token, value["identifier"]))
            else:
                need(value == {})
                await anyio.to_thread.run_sync(lambda: service.logout(token))
            result = response({"ok": True})
            if action == "logout":
                result.delete_cookie(
                    COOKIE, secure=True, httponly=True, samesite="strict", path="/"
                )
            return result
        except (AdminError, ServerError) as exc:
            return response({"code": exc.code}, exc.status)
        except LicenseError:
            return response({"code": "invalid_input"}, 422)
        except Exception:
            return response({"code": "service_unavailable"}, 503)
        finally:
            if acquired:
                slots.release()

    return app
