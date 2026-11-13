"""Run the packaged application on loopback, with a native-only session capability."""

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from pwd import getpwuid

import psycopg
import uvicorn
from psycopg import sql
from sqlalchemy import URL

PAYLOAD = Path(__file__).resolve().parent
sys.path.insert(0, str(PAYLOAD / "app/frontend"))
from aira_host import build_app

from ara.desktop.access import LicensedApplication, new_session_token
from ara.desktop.data_home import open_home
from ara.model_protection.integration import make_license_client
from ara.model_protection.bundle import configuration


class NativeApplication:
    """Expose the page and assets separately from the protected product API."""

    def __init__(self, app, client, origin, token):
        self.app = app
        self.protected = LicensedApplication(app, client, origin=origin, session_token=token)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and (
            path in {"/aira", "/aira/", "/aira/diagnostics/log", "/aira/diagnostics/client"}
            or path.startswith(("/aira/assets/", "/aira/client/"))
        ):
            await self.app(scope, receive, send)
            return
        await self.protected(scope, receive, send)


class ReadyServer(uvicorn.Server):
    def __init__(self, config, handshake, connection):
        super().__init__(config)
        self.handshake = handshake
        self.connection = connection

    async def startup(self, sockets=None):
        await super().startup(sockets)
        if self.started:
            self.handshake.write(json.dumps(self.connection) + "\n")
            self.handshake.close()


def run_pg(bin_dir, *args, timeout=45):
    subprocess.run(
        [str(bin_dir / args[0]), *map(str, args[1:])],
        check=True, stdin=subprocess.DEVNULL, timeout=timeout,
    )


def serve(data, license_origin, handshake):
    home = open_home(data / "state")
    postgres = home.path("postgres")
    cluster = postgres / "cluster"
    pg = PAYLOAD / "pgsql/bin"
    user = getpwuid(os.getuid()).pw_name
    client = None
    try:
        models = PAYLOAD / "app/backend/ml_bundle/models"
        client = make_license_client(license_origin, home.path("license"), models)
        if not cluster.exists():
            with tempfile.TemporaryDirectory(dir=postgres) as staging:
                initialized = Path(staging) / "cluster"
                run_pg(pg, "initdb", "-D", initialized, "-U", user, "--encoding=UTF8",
                       "--locale=C", "--auth-local=peer", "--auth-host=scram-sha-256")
                initialized.rename(cluster)
        with tempfile.TemporaryDirectory(prefix="aira-pg-", dir="/private/tmp") as sock_path:
            # The database is reachable only through this private Unix socket.
            port = 5432
            started = False
            try:
                run_pg(pg, "pg_ctl", "-D", cluster, "-l", postgres / "postgres.log",
                       "-w", "-t", 20, "-o",
                       f"-h '' -k {sock_path} -p {port} -c unix_socket_permissions=0700 -c shared_buffers=32MB", "start")
                started = True
                with psycopg.connect(host=sock_path, user=user, dbname="postgres",
                                     autocommit=True, connect_timeout=5) as admin:
                    if not admin.execute("SELECT 1 FROM pg_database WHERE datname = 'aira'").fetchone():
                        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier("aira")))
                url = URL.create("postgresql+psycopg", username=user, database="aira",
                                 query={"host": sock_path, "port": str(port)})
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    http_port = listener.getsockname()[1]
                    origin = f"http://127.0.0.1:{http_port}"
                    token = new_session_token()
                    app = build_app(database_url=url.render_as_string(hide_password=False),
                                    runtime_root=home.path("analysis"), port=http_port,
                                    analysis="model", native_token=token.hex(), log_file=data / "aira.log",
                                    model_key_provider=client.require_model_key if configuration(models) else None)
                    client.start()
                    config = uvicorn.Config(NativeApplication(app, client, origin, token),
                                            host="127.0.0.1", port=http_port, proxy_headers=False,
                                            access_log=False)
                    ReadyServer(config, handshake, app.state.aira_connection).run(sockets=[listener])
            finally:
                if started:
                    run_pg(pg, "pg_ctl", "-D", cluster, "-w", "-t", 25, "-m", "fast", "stop")
    finally:
        if client is not None and not client.shutdown(timeout=5):
            raise RuntimeError("License cleanup was not confirmed")
        if not home.close():
            raise RuntimeError("Data home cleanup was not confirmed")


def main():
    # stdout is a private pipe to the native parent. Logs go to stderr.
    handshake = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        data = Path(sys.argv[1]).resolve(strict=True)
        config = PAYLOAD.parent / "license-origin.txt"
        origin = config.read_text(encoding="ascii").strip()
        serve(data, origin, handshake)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print("AIRA startup/cleanup failed:", type(error).__name__, getattr(error, "code", ""), file=sys.stderr)
        return 1
    finally:
        handshake.close()


if __name__ == "__main__":
    raise SystemExit(main())
