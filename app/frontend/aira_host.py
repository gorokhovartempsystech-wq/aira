"""Сборка локального сервера AIRA для фронтенда: dev-стенд и установленное приложение.

Собирает то же приложение, что app/backend/scripts/serve_local_model.py (бэкенд не меняется),
и раздаёт с того же origin:

    /aira/              фронтенд (app/frontend/static)
    /aira/client/       клиентские модули app/backend/src/ara/desktop/client
    /aira/connection    origin и токен сессии для страницы (пока нет нативной оболочки)

Синтетический локальный пользователь и PostgreSQL без пароля на 127.0.0.1. Это пилотный
хост, а не продакшен-оболочка с доверенным мостом и лицензированием.
"""

import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

FRONTEND = Path(__file__).resolve().parent
BACKEND = FRONTEND.parent / "backend"
if str(BACKEND / "src") not in sys.path:
    sys.path.insert(0, str(BACKEND / "src"))

USER, PROJECT, INSTALL = (UUID(int=i) for i in (501, 502, 503))
NO_STORE = {"Cache-Control": "no-store"}

# Последние строки диагностики — чтобы журнал можно было скачать из интерфейса и без файла (dev-стенд).
from collections import deque  # noqa: E402

DIAG = deque(maxlen=3000)


def diag(line):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}"
    DIAG.append(line)
    print(line, flush=True)


def private_root(root: Path) -> Path:
    """Каталог воркера анализа, доступный только текущему пользователю."""
    root = Path(root).resolve()
    if root.is_dir():
        return root
    if sys.platform == "win32":
        import ctypes

        from ara.docx_analysis_worker.windows import _abi, _paths, _security

        fs = _paths.NativeFilesystem()
        create = fs.native.kernel.CreateDirectoryW
        create.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_abi.SECURITY_ATTRIBUTES)]
        create.restype = _abi.BOOL
        with _security.descriptor(fs.native, fs.user(), directory=True) as sa:
            if not create(str(root), ctypes.byref(sa)):
                raise RuntimeError("Cannot create private runtime directory")
    else:
        root.mkdir(mode=0o700)
    return root


def init_database(engine):
    """Миграции до head, локальный пользователь и проект, учёт воркера. Повторный вызов безопасен."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from ara.docx_analysis_worker.supervisor import ledger

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        conn.execute(text("INSERT INTO users(id) VALUES(:id) ON CONFLICT DO NOTHING"), {"id": USER})
        conn.execute(text("INSERT INTO projects(id,owner_id,name) VALUES(:id,:owner,'AIRA') ON CONFLICT DO NOTHING"),
                     {"id": PROJECT, "owner": USER})
    fence = ledger.read_fence(engine)
    if fence.phase == "unprovisioned":
        ledger.provision_new_database(engine, installation_id=INSTALL, expected_revision=fence.revision)


class OnboardingStore:
    """Two local preferences, outside the replaceable app and managed database home."""

    def __init__(self, path):
        import threading

        self.path = Path(path) if path is not None else None
        self.lock = threading.RLock()

    def read(self):
        import json

        if self.path is None:
            raise OSError("Onboarding profile is not configured")
        with self.lock:
            try:
                with self.path.open("rb") as stream:
                    raw = stream.read(1025)
            except FileNotFoundError:
                return {"start": "new", "doc": "new"}
            if len(raw) > 1024:
                raise ValueError("Invalid onboarding state")
            state = json.loads(raw)
            if not isinstance(state, dict) or state.get("schema_version") != 1:
                raise ValueError("Invalid onboarding state")
            result = {key: state.get(key, "new") for key in ("start", "doc")}
            if any(value not in ("new", "completed", "dismissed") for value in result.values()):
                raise ValueError("Invalid onboarding state")
            return result

    def mark(self, kind, status):
        import json
        import os
        import tempfile

        if kind not in ("start", "doc") or status not in ("completed", "dismissed"):
            raise ValueError("Invalid onboarding choice")
        with self.lock:
            try:
                state = self.read()
            except (ValueError, UnicodeError):
                state = {"start": "new", "doc": "new"}
            if state[kind] != "completed":
                state[kind] = status
            self.path.parent.mkdir(parents=True, exist_ok=True)
            pending = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=".onboarding-",
                    delete=False,
                ) as stream:
                    pending = Path(stream.name)
                    json.dump({"schema_version": 1, **state}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(pending, self.path)
            finally:
                if pending is not None:
                    pending.unlink(missing_ok=True)
            return state


class UpdateFeed:
    """Read public release metadata; only the native updater may download/install."""

    def __init__(self, config):
        import threading

        self.config = config
        self.lock = threading.Lock()
        self.cached = None
        self.checked_at = 0

    @staticmethod
    def version(value):
        import re

        if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", value
        ):
            raise ValueError("Invalid release version")
        return tuple(map(int, value.split(".")))

    def parse(self, raw):
        from urllib.parse import urlsplit
        from xml.etree import ElementTree as ET

        if len(raw) > 65536 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("Invalid update feed")
        config = self.config
        current = self.version(config["version"])
        is_mac = config["platform"] == "macos-arm64"
        current_order = int(config["build"]) if is_mac else current
        best_order, latest, valid_entries = current_order, config["version"], 0
        source = urlsplit(config["feed_url"])
        ns = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
        try:
            items = ET.fromstring(raw).findall("./channel/item")
        except ET.ParseError:
            raise ValueError("Invalid update feed") from None
        if not items:
            raise ValueError("Empty update feed")
        for item in items:
            entry = item.find("enclosure")
            if entry is None:
                continue
            if not is_mac and entry.get(ns + "os") != "windows-x64":
                continue
            target = urlsplit(entry.get("url", ""))
            if (target.scheme, target.netloc) != (
                source.scheme,
                source.netloc,
            ) or not target.path.startswith("/downloads/"):
                continue
            if (
                target.username
                or target.password
                or target.query
                or target.fragment
                or not entry.get(ns + "edSignature")
            ):
                continue
            name = entry.get(ns + "shortVersionString", "")
            try:
                version = self.version(name)
                order = int(entry.get(ns + "version", "")) if is_mac else version
            except (ValueError, TypeError):
                continue
            valid_entries += 1
            if order > best_order and version >= current:
                best_order, latest = order, name
        if not valid_entries:
            raise ValueError("No valid releases in update feed")
        return {
            "status": "available" if best_order > current_order else "current",
            "current_version": config["version"],
            "latest_version": latest,
            "platform": config["platform"],
        }

    def snapshot(self, *, refresh=False):
        from urllib.parse import urlsplit
        from urllib.request import HTTPRedirectHandler, Request, build_opener

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        with self.lock:
            if not refresh and self.cached is not None and time.monotonic() - self.checked_at < 300:
                return self.cached
            config = self.config
            if not config or config.get("platform") not in ("windows-x64", "macos-arm64"):
                raise ValueError("Updates are not configured")
            url = urlsplit(config["feed_url"])
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path != "/updates/" + config["platform"] + ".xml"
            ):
                raise ValueError("Invalid update feed URL")
            request = Request(
                config["feed_url"],
                headers={"Accept": "application/xml", "Cache-Control": "no-cache"},
            )
            with build_opener(NoRedirect()).open(request, timeout=5) as response:
                raw = response.read(65537)
            self.cached = self.parse(raw)
            self.checked_at = time.monotonic()
            return self.cached


def frontend_routes(app, port, *, dev=False, dev_pages=None, log_file=None, token=None, native_only=False,
                    onboarding_path=None, app_update=None):
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    token = token if token is not None else secrets.token_hex(32)
    # Окну приложения (pywebview) запускатель передаёт это через мост, а не через /aira/connection.
    app.state.aira_connection = {"origin": f"http://127.0.0.1:{port}", "sessionToken": token}
    onboarding = OnboardingStore(onboarding_path)
    updates = UpdateFeed(app_update)

    @app.get("/aira/onboarding", include_in_schema=False)
    def read_onboarding(request: Request):
        if not secrets.compare_digest(request.headers.get("x-aira-session", ""), token):
            return JSONResponse({"code": "forbidden"}, status_code=403, headers=NO_STORE)
        try:
            return JSONResponse(onboarding.read(), headers=NO_STORE)
        except (OSError, ValueError, UnicodeError):
            return JSONResponse({"code": "onboarding_unavailable"}, status_code=503, headers=NO_STORE)

    @app.post("/aira/onboarding/{kind}", include_in_schema=False)
    async def mark_onboarding(kind: str, request: Request):
        if not secrets.compare_digest(request.headers.get("x-aira-session", ""), token):
            return JSONResponse({"code": "forbidden"}, status_code=403, headers=NO_STORE)
        import json

        try:
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 128:
                    raise ValueError("Invalid onboarding choice")
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"status"}:
                raise ValueError("Invalid onboarding choice")
            return JSONResponse(onboarding.mark(kind, body["status"]), headers=NO_STORE)
        except (ValueError, UnicodeError, TypeError):
            return JSONResponse({"code": "invalid_onboarding_choice"}, status_code=422, headers=NO_STORE)
        except OSError:
            return JSONResponse({"code": "onboarding_unavailable"}, status_code=503, headers=NO_STORE)

    @app.get("/aira/updates", include_in_schema=False)
    def read_updates(request: Request):
        if not secrets.compare_digest(request.headers.get("x-aira-session", ""), token):
            return JSONResponse({"code": "forbidden"}, status_code=403, headers=NO_STORE)
        try:
            return JSONResponse(updates.snapshot(refresh=request.query_params.get("refresh") == "1"), headers=NO_STORE)
        except Exception:
            return JSONResponse({"code": "update_check_unavailable"}, status_code=503, headers=NO_STORE)

    @app.get("/aira/diagnostics/log", include_in_schema=False)
    def download_log(request: Request):
        # Журнал для разработчиков: окружение, запуски и отказы проверки. Только для страницы AIRA (токен сессии).
        if not secrets.compare_digest(request.headers.get("x-aira-session", ""), token):
            return JSONResponse({"code": "forbidden"}, status_code=403, headers=NO_STORE)
        text = ""
        if log_file and Path(log_file).is_file():
            raw = Path(log_file).read_bytes()[-3_000_000:]
            text = raw.decode("utf-8", errors="replace")
        else:
            text = "\n".join(DIAG) + "\n"
        name = f"aira-log-{time.strftime('%Y%m%d-%H%M')}.txt"
        return PlainTextResponse(text, headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/aira/diagnostics/client", include_in_schema=False)
    async def client_event(request: Request):
        # Что увидел пользователь: сообщения сурката и ошибки интерфейса — в тот же журнал.
        if not secrets.compare_digest(request.headers.get("x-aira-session", ""), token):
            return JSONResponse({"code": "forbidden"}, status_code=403, headers=NO_STORE)
        import json

        try:
            data = json.loads((await request.body())[:4000] or b"{}")
        except ValueError:
            data = {}
        if isinstance(data, dict):
            kind, message = str(data.get("kind", ""))[:20], str(data.get("message", ""))[:800].replace("\n", " ")
            diag(f"[ui] {kind}: {message}")
        return JSONResponse({}, headers=NO_STORE)

    @app.get("/aira/connection", include_in_schema=False)
    def connection():
        if native_only:
            return JSONResponse({"code": "route_unavailable"}, status_code=404, headers=NO_STORE)
        # Нативная оболочка передаст это через доверенный мост, а не по HTTP.
        return JSONResponse({"origin": f"http://127.0.0.1:{port}", "sessionToken": token, "dev": dev},
                            headers=NO_STORE)

    @app.get("/aira", include_in_schema=False)
    def root_redirect():
        return RedirectResponse("/aira/")

    @app.get("/", include_in_schema=False)
    def site_root():
        return RedirectResponse("/aira/")

    @app.get("/aira/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND / "static" / "index.html", headers=NO_STORE)

    if dev_pages and Path(dev_pages).is_dir():
        app.mount("/aira/dev-pages", StaticFiles(directory=dev_pages), name="aira-dev-pages")
    app.mount("/aira/client", StaticFiles(directory=BACKEND / "src/ara/desktop/client"), name="aira-client")
    app.mount("/aira/assets", StaticFiles(directory=FRONTEND / "static"), name="aira-assets")


def licence_stub_routes(app):
    """Только dev-стенд: имитация экрана лицензии. Ключ USED… — «на другом устройстве», короче 16 — «не найден»."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    licence = {"phase": "activation_required", "error_code": None, "license_id": None, "expires_at_ms": None}

    def snapshot():
        return {"schema_version": "aira-desktop-license/1", **licence,
                "retry_available": licence["phase"] in ("failed",),
                "preservation_available": licence["phase"] == "active"}

    @app.get("/desktop/license", include_in_schema=False)
    def licence_state():
        return JSONResponse(snapshot(), headers=NO_STORE)

    @app.post("/desktop/license/activate", include_in_schema=False)
    async def licence_activate(request: Request):
        body = await request.json()
        key = str(body.get("license_key", "")).strip().upper()
        if key.startswith("USED"):
            licence.update(phase="failed", error_code="device_mismatch")
        elif len(key.replace("-", "")) < 16:
            licence.update(phase="failed", error_code="invalid_license")
        else:
            licence.update(phase="active", error_code=None, license_id="dev-licence",
                           expires_at_ms=str(int((time.time() + 90 * 86400) * 1000)))
        return JSONResponse(snapshot(), status_code=202, headers=NO_STORE)

    @app.post("/desktop/license/verify", include_in_schema=False)
    def licence_verify():
        return JSONResponse(snapshot(), status_code=202, headers=NO_STORE)


def build_app(*, database_url, runtime_root, port, analysis="model", initialize=True,
              licence_stub=False, dev=False, dev_pages=None, on_ready=None, log_file=None,
              native_token=None, model_key_provider=None, startup_progress=None,
              on_startup_error=None, database_connect_args=None, onboarding_path=None, app_update=None):
    """Возвращает ASGI-приложение. Воркер анализа запускается и останавливается в lifespan."""
    from sqlalchemy import create_engine

    from ara.app import create_app
    from ara.config import DatabaseSettings
    from ara.documents.runtime import DocumentRuntime

    root = private_root(runtime_root)
    settings = DatabaseSettings(database_url)
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True,
                           connect_args=database_connect_args or {})
    if initialize:
        if startup_progress:
            startup_progress("database")
        try:
            init_database(engine)
        except BaseException:
            engine.dispose()
            raise

    runtime = DocumentRuntime(engine=engine, user_id=USER, project_id=PROJECT, mode="local")
    if analysis == "model":
        from ara.docx_analysis_worker.supervisor.local_model import create_local_model_supervisor as factory
    else:
        from ara.docx_analysis_worker.supervisor.word_fixture import create_word_fixture_supervisor as factory
    if startup_progress:
        startup_progress("model_package")
    options = {"model_key_provider": model_key_provider} if analysis == "model" and model_key_provider is not None else {}
    if startup_progress and analysis == "model":
        options["startup_checkpoint"] = startup_progress
    try:
        supervisor = factory(settings=settings, user_id=USER, project_id=PROJECT, installation_id=INSTALL, root=root, **options)
    except BaseException:
        engine.dispose()
        raise
    if startup_progress:
        startup_progress("routes")
    app = create_app(document_runtime=runtime, analysis_supervisor=supervisor, table_editor=True, field_editor=True)
    if licence_stub:
        licence_stub_routes(app)
    frontend_routes(app, port, dev=dev, dev_pages=dev_pages, log_file=log_file,
                    token=native_token, native_only=native_token is not None,
                    onboarding_path=onboarding_path, app_update=app_update)
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        import anyio

        started = False
        try:
            supervisor.start()
            deadline = time.monotonic() + 60
            while supervisor.view().phase != "ready":
                view = supervisor.view()
                if view.error_code or time.monotonic() > deadline:
                    raise SupervisorError(view.error_code or "startup_timeout", view)
                await anyio.sleep(0.05)
            if on_ready:
                on_ready()
            async with previous(application):
                started = True
                yield
        except BaseException as error:
            if not started and on_startup_error is not None:
                on_startup_error(error)
            raise
        finally:
            deadline = time.monotonic() + 30
            while not supervisor.shutdown(timeout=0.1):
                if time.monotonic() > deadline:
                    raise RuntimeError("Analysis supervisor cleanup not confirmed")
            engine.dispose()

    app.router.lifespan_context = lifespan
    app.add_middleware(DiagnosticLog)
    return app


class DiagnosticLog:
    """ASGI-прослойка для журнала (stdout → aira.log): запуски и отказы проверки, ошибки API с кодами.
    Без токена сессии, тел запросов и текста документов; опросы идущей проверки не пишутся."""

    QUIET_PHASES = {"admitting", "queued", "active", "settling"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith(("/docx-documents", "/documents")):
            return await self.app(scope, receive, send)
        import json

        path, method = scope["path"], scope.get("method", "")
        started = time.monotonic()
        operation = method in {"POST", "PUT", "PATCH", "DELETE"} and not path.endswith("/working-content")
        analysis = "/analysis-" in path
        state = {"status": 0, "body": b""}

        async def capture(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
            elif message["type"] == "http.response.body" and (analysis or state["status"] >= 400):
                if len(state["body"]) < 8192:
                    state["body"] += message.get("body", b"")[:8192]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            status = state["status"]
            if analysis or operation or status >= 400:
                try:
                    data = json.loads(state["body"] or b"{}")
                except ValueError:
                    data = {}
                run = data.get("state") or {} if isinstance(data, dict) else {}
                phase = data.get("phase") if isinstance(data, dict) else None
                quiet = (analysis and method == "GET" and status < 400 and phase in self.QUIET_PHASES) or (
                    status == 404 and path.endswith("/analysis-review"))  # проверки ещё не было — это не ошибка
                if not quiet:
                    fields = {k: v for k, v in {
                        "phase": phase, "error_code": data.get("error_code") if isinstance(data, dict) else None,
                        "code": data.get("code") if isinstance(data, dict) else None,
                        "run_status": run.get("status"), "run_error": run.get("error_code"),
                        "execution": run.get("execution_kind")}.items() if v}
                    diag(f"[api] {method} {path} -> {status} {fields} duration_ms={round((time.monotonic() - started) * 1000)}")


class SupervisorError(RuntimeError):
    def __init__(self, code, view):
        super().__init__(f"Analysis supervisor did not start: {view}")
        self.code = code
