"""Local development stand for the AIRA frontend (Windows/macOS).

Builds the same application as app/backend/scripts/serve_local_model.py and additionally
serves the frontend and the desktop client modules from the same origin:

    /aira/          frontend (app/frontend/static)
    /aira/client/   app/backend/src/ara/desktop/client/*.mjs

Analysis modes:
    --analysis fixture  explicit test analysis (no model weights needed, marked as fixture)
    --analysis model    real local model from app/backend/ml_bundle

Development only: a synthetic local user, passwordless loopback PostgreSQL and a fake
licence endpoint. This is not the production native host and not a licence implementation.

Run from app/backend with the *base* Python 3.12 that has requirements.lock installed:
    python ..\\frontend\\dev\\serve_dev.py --runtime-root C:\\AIRA-dev-runtime \\
        --pg-port 15435 --initialize-test-database

On Windows do not use .venv\\Scripts\\python.exe: it is a redirecting launcher, and the
native analysis worker started through it exits without a result (adapter_error).
"""

import argparse
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

FRONTEND = Path(__file__).resolve().parents[1]
BACKEND = FRONTEND.parent / "backend"


def private_root(root: Path) -> Path:
    root = root.resolve()
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


def dev_routes(app, port):
    """Dev-only helpers: connection details for the page and a fake licence state."""
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    token = secrets.token_hex(32)
    licence = {"phase": "activation_required", "error_code": None, "license_id": None,
               "expires_at_ms": None}

    def snapshot():
        return {"schema_version": "aira-desktop-license/1", **licence,
                "retry_available": licence["phase"] in ("failed",),
                "preservation_available": licence["phase"] == "active"}

    no_store = {"Cache-Control": "no-store"}

    @app.get("/aira/dev/connection", include_in_schema=False)
    def connection():
        # The real native host passes these through a trusted bridge, never over HTTP.
        return JSONResponse({"origin": f"http://127.0.0.1:{port}", "sessionToken": token,
                             "dev": True}, headers=no_store)

    @app.get("/desktop/license", include_in_schema=False)
    def licence_state():
        return JSONResponse(snapshot(), headers=no_store)

    @app.post("/desktop/license/activate", include_in_schema=False)
    async def licence_activate(request: Request):
        body = await request.json()
        key = str(body.get("license_key", "")).strip().upper()
        if key.startswith("USED"):
            licence.update(phase="failed", error_code="device_mismatch")
        elif len(key.replace("-", "")) < 16:
            licence.update(phase="failed", error_code="invalid_license")
        else:
            expires = int((time.time() + 90 * 86400) * 1000)
            licence.update(phase="active", error_code=None, license_id="dev-licence",
                           expires_at_ms=str(expires))
        return JSONResponse(snapshot(), status_code=202, headers=no_store)

    @app.post("/desktop/license/verify", include_in_schema=False)
    def licence_verify():
        return JSONResponse(snapshot(), status_code=202, headers=no_store)

    @app.get("/aira", include_in_schema=False)
    def root_redirect():
        return RedirectResponse("/aira/")

    @app.get("/aira/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND / "static" / "index.html", headers=no_store)

    pages = FRONTEND / "dev" / "pages"
    if pages.is_dir():
        # Same-origin test pages (UI smoke scenarios); development stand only.
        app.mount("/aira/dev-pages", StaticFiles(directory=pages), name="aira-dev-pages")
    app.mount("/aira/client", StaticFiles(directory=BACKEND / "src/ara/desktop/client"),
              name="aira-client")
    app.mount("/aira/assets", StaticFiles(directory=FRONTEND / "static"), name="aira-assets")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8017)
    parser.add_argument("--pg-port", type=int, default=15435)
    parser.add_argument("--analysis", choices=("fixture", "model"), default="fixture")
    parser.add_argument("--database", default="aira_native_test")
    parser.add_argument("--initialize-test-database", action="store_true")
    args = parser.parse_args()
    if not (1024 <= args.port <= 65535 and 1024 <= args.pg_port <= 65535):
        raise ValueError("Invalid local port")

    sys.path.insert(0, str(BACKEND / "src"))
    import uvicorn
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from ara.app import create_app
    from ara.config import DatabaseSettings
    from ara.docx_analysis_worker.supervisor import ledger
    from ara.documents.runtime import DocumentRuntime

    root = private_root(args.runtime_root)
    settings = DatabaseSettings(
        f"postgresql+psycopg://postgres@127.0.0.1:{args.pg_port}/{args.database}"
    )
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    user, project, install = (UUID(int=i) for i in (501, 502, 503))
    if args.initialize_test_database:
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            conn.execute(text("INSERT INTO users(id) VALUES(:id) ON CONFLICT DO NOTHING"),
                         {"id": user})
            conn.execute(
                text("INSERT INTO projects(id,owner_id,name) "
                     "VALUES(:id,:owner,'AIRA frontend dev') ON CONFLICT DO NOTHING"),
                {"id": project, "owner": user},
            )
        fence = ledger.read_fence(engine)
        if fence.phase == "unprovisioned":
            ledger.provision_new_database(engine, installation_id=install,
                                          expected_revision=fence.revision)

    runtime = DocumentRuntime(engine=engine, user_id=user, project_id=project, mode="local")
    if args.analysis == "model":
        from ara.docx_analysis_worker.supervisor.local_model import (
            create_local_model_supervisor as factory,
        )
    else:
        from ara.docx_analysis_worker.supervisor.word_fixture import (
            create_word_fixture_supervisor as factory,
        )
    supervisor = factory(settings=settings, user_id=user, project_id=project,
                         installation_id=install, root=root)
    app = create_app(document_runtime=runtime, analysis_supervisor=supervisor,
                     table_editor=True, field_editor=True)
    dev_routes(app, args.port)
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        import anyio

        supervisor.start()
        try:
            deadline = time.monotonic() + 20
            while supervisor.view().phase != "ready":
                if supervisor.view().error_code or time.monotonic() > deadline:
                    raise RuntimeError(f"Analysis supervisor did not start: {supervisor.view()}")
                await anyio.sleep(0.05)
            print(f"AIRA dev: http://127.0.0.1:{args.port}/aira/  (analysis={args.analysis})",
                  flush=True)
            async with previous(application):
                yield
        finally:
            deadline = time.monotonic() + 30
            while not supervisor.shutdown(timeout=0.1):
                if time.monotonic() > deadline:
                    raise RuntimeError("Analysis supervisor cleanup not confirmed")
            engine.dispose()

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
