"""Explicit Windows development stand: separate local test DB and native real worker."""

import argparse
import ctypes
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID


def main():
    import uvicorn
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from ara.app import create_app
    from ara.config import DatabaseSettings
    from ara.documents.runtime import DocumentRuntime
    from ara.docx_analysis_worker.supervisor.local_model import create_local_model_supervisor
    from ara.docx_analysis_worker.windows import _abi, _paths, _security

    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8017)
    parser.add_argument("--pg-port", type=int, default=15435)
    parser.add_argument("--initialize-test-database", action="store_true")
    args = parser.parse_args()
    if not (1024 <= args.port <= 65535 and 1024 <= args.pg_port <= 65535):
        raise ValueError("Invalid local test port")
    root = args.runtime_root.resolve()
    if not root.is_dir():
        fs = _paths.NativeFilesystem()
        create = fs.native.kernel.CreateDirectoryW
        create.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_abi.SECURITY_ATTRIBUTES)]
        create.restype = _abi.BOOL
        with _security.descriptor(fs.native, fs.user(), directory=True) as sa:
            if not create(str(root), ctypes.byref(sa)):
                raise RuntimeError("Cannot create private test runtime directory")
    settings = DatabaseSettings(
        f"postgresql+psycopg://postgres@127.0.0.1:{args.pg_port}/aira_native_test"
    )
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    user, project, install = (UUID(int=i) for i in (501, 502, 503))
    base = Path(__file__).resolve().parents[1]
    if args.initialize_test_database:
        config = Config(str(base / "alembic.ini"))
        config.set_main_option("script_location", str(base / "migrations"))
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            conn.execute(
                text("INSERT INTO users(id) VALUES(:id) ON CONFLICT DO NOTHING"), {"id": user}
            )
            conn.execute(
                text(
                    "INSERT INTO projects(id,owner_id,name) "
                    "VALUES(:id,:owner,'Native model test') ON CONFLICT DO NOTHING"
                ),
                {"id": project, "owner": user},
            )
    from ara.docx_analysis_worker.supervisor import ledger

    fence = ledger.read_fence(engine)
    if args.initialize_test_database and fence.phase == "unprovisioned":
        ledger.provision_new_database(
            engine, installation_id=install, expected_revision=fence.revision
        )
    runtime = DocumentRuntime(engine=engine, user_id=user, project_id=project, mode="local")
    supervisor = create_local_model_supervisor(
        settings=settings, user_id=user, project_id=project, installation_id=install, root=root
    )
    app = create_app(
        document_runtime=runtime,
        analysis_supervisor=supervisor,
        table_editor=True,
        field_editor=True,
    )
    from ara.team_editor import install_team_editor

    install_team_editor(app)
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        supervisor.start()
        try:
            import anyio

            deadline = time.monotonic() + 20
            while supervisor.view().phase != "ready":
                if supervisor.view().error_code or time.monotonic() > deadline:
                    raise RuntimeError(f"Native supervisor startup failed: {supervisor.view()}")
                await anyio.sleep(0.05)
            async with previous(application):
                yield
        finally:
            deadline = time.monotonic() + 30
            while not supervisor.shutdown(timeout=0.1):
                if time.monotonic() > deadline:
                    raise RuntimeError("Native cleanup not confirmed")
            engine.dispose()

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
