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


def frontend_routes(app, port, *, dev=False, dev_pages=None):
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    token = secrets.token_hex(32)

    @app.get("/aira/connection", include_in_schema=False)
    def connection():
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
              licence_stub=False, dev=False, dev_pages=None, on_ready=None):
    """Возвращает ASGI-приложение. Воркер анализа запускается и останавливается в lifespan."""
    from sqlalchemy import create_engine

    from ara.app import create_app
    from ara.config import DatabaseSettings
    from ara.documents.runtime import DocumentRuntime

    root = private_root(runtime_root)
    settings = DatabaseSettings(database_url)
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    if initialize:
        init_database(engine)

    runtime = DocumentRuntime(engine=engine, user_id=USER, project_id=PROJECT, mode="local")
    if analysis == "model":
        from ara.docx_analysis_worker.supervisor.local_model import create_local_model_supervisor as factory
    else:
        from ara.docx_analysis_worker.supervisor.word_fixture import create_word_fixture_supervisor as factory
    supervisor = factory(settings=settings, user_id=USER, project_id=PROJECT, installation_id=INSTALL, root=root)
    app = create_app(document_runtime=runtime, analysis_supervisor=supervisor, table_editor=True, field_editor=True)
    if licence_stub:
        licence_stub_routes(app)
    frontend_routes(app, port, dev=dev, dev_pages=dev_pages)
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        import anyio

        supervisor.start()
        try:
            deadline = time.monotonic() + 60
            while supervisor.view().phase != "ready":
                view = supervisor.view()
                if view.error_code or time.monotonic() > deadline:
                    raise SupervisorError(view.error_code or "startup_timeout", view)
                await anyio.sleep(0.05)
            if on_ready:
                on_ready()
            async with previous(application):
                yield
        finally:
            deadline = time.monotonic() + 30
            while not supervisor.shutdown(timeout=0.1):
                if time.monotonic() > deadline:
                    raise RuntimeError("Analysis supervisor cleanup not confirmed")
            engine.dispose()

    app.router.lifespan_context = lifespan
    return app


class SupervisorError(RuntimeError):
    def __init__(self, code, view):
        super().__init__(f"Analysis supervisor did not start: {view}")
        self.code = code
