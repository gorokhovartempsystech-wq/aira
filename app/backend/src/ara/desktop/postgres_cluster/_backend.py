"""One worker owns journal IO, SQL and the foreground PostgreSQL command."""

import os
import platform
import sys
from uuid import uuid4

from ara.desktop.postgres_process import OwnedCommand
from ara.desktop.postgres_profile import OBSERVATION_SQL, check_observation, make_plan

from . import _journal
from ._filesystem import Filesystem
from ._models import ClusterError, ClusterIdentity, require

# Read presence only. Neither inherited service files nor a user's libpq defaults
# may redirect this internal connection; the launcher will use a narrow env too.
LIBPQ_ENV = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGPASSFILE",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGSYSCONFDIR",
    "PGOPTIONS",
    "PGAPPNAME",
    "PGCONNECT_TIMEOUT",
    "PGCLIENTENCODING",
    "PGTARGETSESSIONATTRS",
    "PGLOADBALANCEHOSTS",
    "PGCHANNELBINDING",
    "PGREQUIREAUTH",
    "PGREQUIREPEER",
    "PGMINPROTOCOLVERSION",
    "PGMAXPROTOCOLVERSION",
    "PGLOCALEDIR",
    "PGSSLMODE",
    "PGREQUIRESSL",
    "PGSSLCOMPRESSION",
    "PGSSLCERT",
    "PGSSLKEY",
    "PGSSLCERTMODE",
    "PGSSLROOTCERT",
    "PGSSLCRL",
    "PGSSLCRLDIR",
    "PGSSLSNI",
    "PGSSLMINPROTOCOLVERSION",
    "PGSSLMAXPROTOCOLVERSION",
    "PGSSLNEGOTIATION",
    "PGGSSENCMODE",
    "PGKRBSRVNAME",
    "PGGSSLIB",
    "PGGSSDELEGATION",
    "PGHOSTREQUIRE",
    "PGKEEPALIVES",
    "PGKEEPALIVESIDLE",
    "PGKEEPALIVESINTERVAL",
    "PGKEEPALIVESCOUNT",
    "PGTCPUSER_TIMEOUT",
    "PGDATESTYLE",
    "PGTZ",
    "PGGEQO",
)

DATABASE_SQL = """
SELECT d.oid::bigint, r.rolname, pg_catalog.pg_encoding_to_char(d.encoding),
       d.datcollate, d.datctype, d.datallowconn, d.datistemplate
FROM pg_catalog.pg_database AS d JOIN pg_catalog.pg_roles AS r ON r.oid = d.datdba
WHERE d.datname = 'aira'
"""


class Stopped(Exception):
    pass


class Backend:
    def __init__(self, runtime):
        self.runtime = runtime
        self.home, self.tools = runtime._home, runtime._tools
        self.installation = self.home.identity().installation_id
        self.fs = self.owner = self.command = self.sql = None
        self.plan = self.clock = self.deadline = None
        self.uncertain = False
        self.orphans = []

    def check(self):
        if self.runtime._stop.is_set():
            raise Stopped()
        require(self.home.view().phase == "open", "invalid_handle")
        if self.clock is not None:
            require(self.clock.now_ns() < self.deadline, "startup_timeout")

    def run_command(self, executable, arguments, *, capture=False, server=False):
        self.check()
        self.fs.recheck()
        require(self.command is None, "invalid_handle")
        self.command = OwnedCommand(
            self.owner, executable, arguments, cwd=self.fs.root, capture_stdout=capture
        )
        self.command.start()
        while True:
            self.check()
            view = self.command.view()
            if server and view.phase == "running":
                return
            require(view.error_code is None, "cluster_unavailable")
            if not view.resources_pending:
                require(
                    not server and view.phase == "exited" and view.returncode == 0,
                    "cluster_unavailable",
                )
                output = self.command.stdout() if capture else b""
                require(self.command.shutdown(0), "cleanup_unknown")
                self.command = None
                return output
            self.runtime._stop.wait(0.01)

    def server_live(self):
        require(
            self.command is not None and self.command.view().phase == "running",
            "cluster_unavailable",
        )

    def close_sql(self):
        connection, self.sql = self.sql, None
        if connection is not None:
            try:
                connection.close()
                require(connection.closed, "cleanup_unknown")
            except BaseException:
                self.orphans.append(connection)
                self.uncertain = True
                raise ClusterError("cleanup_unknown") from None

    def connect(self, database, *, retry=False):
        import psycopg

        while True:
            self.check()
            self.server_live()
            try:
                self.sql = psycopg.connect(
                    **dict(self.plan.connection(database)),
                    autocommit=True,
                    options="-c statement_timeout=2000 -c lock_timeout=500",
                )
            except psycopg.OperationalError:
                if not retry:
                    raise ClusterError("cluster_unavailable") from None
                self.runtime._stop.wait(0.025)
                continue
            self.check()
            self.server_live()
            return

    def observation(self, database, system):
        self.check()
        result = self.sql.execute(OBSERVATION_SQL).fetchone()
        require(type(result) is tuple and len(result) == 1)
        try:
            check_observation(
                self.plan, result[0], expected_system_identifier=system, database=database
            )
        except Exception:
            raise ClusterError("cluster_recovery_required") from None
        self.check()
        self.server_live()

    def database(self, system, first, final):
        self.connect("postgres", retry=True)
        try:
            self.observation("postgres", system)
            row = self.sql.execute(DATABASE_SQL).fetchone()
            if row is None:
                require(first)
                self.check()
                self.sql.execute(
                    "CREATE DATABASE aira OWNER aira_local ENCODING 'UTF8' "
                    "LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0"
                )
                row = self.sql.execute(DATABASE_SQL).fetchone()
            require(type(row) is tuple and len(row) == 7)
            oid, owner, encoding, collate, ctype, allowed, template = row
            require(
                type(oid) is int
                and 1 <= oid < 2**32
                and owner == "aira_local"
                and encoding == "UTF8"
                and collate == ctype == "C"
                and allowed is True
                and template is False
            )
            require(first or final["database_oid"] == oid)
        finally:
            self.close_sql()
        self.connect("aira")
        try:
            self.observation("aira", system)
            # A matching physical cluster does not prove that this connection
            # entered the same database observed on the maintenance connection.
            current = self.sql.execute(DATABASE_SQL).fetchone()
            require(current == row and type(current[0]) is int)
        finally:
            self.close_sql()
        _journal.finish(self, system, oid, first)
        return ClusterIdentity(self.installation, system, oid)

    def run(self):
        from ara.docx_analysis_worker.macos import DarwinClock, MacRuntimeError, acquire_owner

        require(sys.platform == "darwin", "platform_unavailable")
        target = {"arm64": "macos-arm64", "x86_64": "macos-x86_64"}.get(platform.machine())
        require(target == self.tools.target, "platform_unavailable")
        require(not any(key in os.environ for key in LIBPQ_ENV), "cluster_unavailable")
        import pwd

        self.clock = DarwinClock()
        self.deadline = self.clock.now_ns() + 120_000_000_000
        self.check()
        self.plan = make_plan(
            target=target,
            installation_id=self.installation,
            postgres_root=str(self.home.path("postgres")),
            system_user=pwd.getpwuid(os.geteuid()).pw_name,
            socket_id=uuid4(),
        )
        self.fs = Filesystem(self.home.path("postgres"))
        self.fs.open()
        try:
            self.owner = acquire_owner(self.fs.root)
        except MacRuntimeError as error:
            if error.code == "runtime_busy":
                raise ClusterError("cluster_busy") from None
            self.uncertain = True
            raise ClusterError("cleanup_unknown") from None
        slot = None
        try:
            slot = self.owner.reserve_slot()
            self.fs.bind(slot)
        except MacRuntimeError as error:
            if error.code == "runtime_busy":
                raise ClusterError("cluster_busy") from None
            self.uncertain = True
            raise ClusterError("cleanup_unknown") from None
        finally:
            if slot is not None:
                try:
                    require(self.owner.release_slot(slot), "cluster_busy")
                except BaseException:
                    self.uncertain = True
                    raise ClusterError("cleanup_unknown") from None
        self.check()
        system, first, final = _journal.prepare(self)
        self.check()
        self.fs.make_socket(self.plan.socket_root)
        self.runtime._phase_to("starting")
        self.run_command(self.tools.postgres, self.plan.postgres_arguments, server=True)
        identity = self.database(system, first, final)
        self.check()
        self.fs.recheck()
        self.runtime._ready(identity, self.plan)
        while not self.runtime._stop.wait(0.05):
            require(self.home.view().phase == "open", "invalid_handle")
            self.server_live()

    def close(self):
        try:
            self.close_sql()
        except BaseException:
            self.uncertain = True
        if self.command is not None:
            while not self.command.shutdown(0.2):
                if self.uncertain or self.command.view().error_code == "cleanup_unknown":
                    return False
            self.command = None
        if self.uncertain:
            return False
        try:
            if self.fs is not None:
                self.fs.close()
            if self.owner is not None:
                owner, self.owner = self.owner, None
                try:
                    owner.close()
                except BaseException:
                    self.orphans.append(owner)
                    raise
            return True
        except BaseException:
            self.uncertain = True
            return False
