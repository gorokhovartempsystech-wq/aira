"""One issued source owns admission and tracks borrowed DBAPI connections until known close."""

import math
import os
import threading
import time
from weakref import WeakSet

from ._models import DatabaseError, DatabaseView, DesktopDatabaseSettings, require

_KEY = object()
_ISSUED = WeakSet()
_REGISTRY = {}
_LOCK = threading.Lock()
_PID = None
CAPS = {"document": 4, "admission": 1, "control": 1, "publication": 1, "analysis_read": 2}


class DatabaseSource:
    def __new__(cls, key=None, *args):
        if key is not _KEY:
            raise TypeError("database sources are issued by bind_database")
        return super().__new__(cls)

    def __init__(self, key, home, cluster, schema, receipt):
        self._pid = os.getpid()
        self._home, self._cluster, self._schema = home, cluster, schema
        self._identity, self._physical, self._receipt = home.identity(), cluster.identity(), receipt
        self._condition = threading.Condition()
        self._raw, self._connecting = {}, {role: 0 for role in CAPS}
        self._stopping = self._closed = self._uncertain = False
        self._document = None
        _ISSUED.add(self)

    def __repr__(self):
        return "<DesktopDatabaseSource>"

    def __copy__(self):
        raise TypeError("process-local database source")

    def __deepcopy__(self, memo):
        raise TypeError("process-local database source")

    def __reduce_ex__(self, protocol):
        raise TypeError("process-local database source")

    def _origin(self):
        require(type(self) is DatabaseSource and self in _ISSUED and self._pid == os.getpid())

    def _live(self):
        try:
            require(
                self._home.identity() == self._identity
                and self._cluster.identity() == self._physical
                and self._schema.receipt() == self._receipt
            )
        except Exception:
            raise DatabaseError("invalid_handle") from None

    def _open(self):
        require(not (self._stopping or self._closed or self._uncertain))

    def _usable(self):
        self._origin()
        self._live()
        with self._condition:
            self._open()

    def _finish(self):
        # Caller owns the condition. Native activity has already reported its
        # outcome, so this only releases metadata ownership, never live SQL.
        if (
            self._stopping
            and not self._raw
            and not any(self._connecting.values())
            and not self._uncertain
        ):
            self._closed = True
            with _LOCK:
                if _REGISTRY.get(self._home) is self:
                    del _REGISTRY[self._home]
        self._condition.notify_all()

    def _unknown(self):
        self._origin()
        with self._condition:
            self._uncertain = self._stopping = True
            self._condition.notify_all()

    def _released(self, raw):
        self._origin()
        with self._condition:
            require(raw in self._raw, "cleanup_unknown")
            del self._raw[raw]
            self._finish()

    def _connect(self, role):
        import psycopg

        from ara.desktop.postgres_cluster import ClusterError
        from ara.desktop.postgres_cluster._backend import LIBPQ_ENV
        from ara.docx_analysis_worker.supervisor.database import OPTIONS

        from ._connection import TrackedConnection, verify

        self._usable()
        require(role in CAPS, "validation_error")
        with self._condition:
            self._open()
            count = self._connecting[role] + sum(value == role for value in self._raw.values())
            require(count < CAPS[role], "database_busy")
            self._connecting[role] += 1
        native_attempted = False
        try:
            require(not any(key in os.environ for key in LIBPQ_ENV), "database_unavailable")
            options = (
                "-c statement_timeout=60000 -c lock_timeout=1000 -c synchronous_commit=on"
                if role == "document"
                else OPTIONS
            )
            parameters = dict(self._cluster.connection())
            native_attempted = True
            raw = TrackedConnection.connect(
                **parameters, options=options + " -c search_path=public,pg_catalog"
            )
        except BaseException as error:
            # Only the driver's documented ordinary connect failure is known
            # after an attempted creation. A typed cleanup error may itself be
            # the result of an unknown native close, so it must retain ownership.
            if native_attempted and not isinstance(error, psycopg.OperationalError):
                self._unknown()
                raise DatabaseError("cleanup_unknown") from None
            with self._condition:
                self._connecting[role] -= 1
                self._finish()
            code = (
                error.code
                if isinstance(error, DatabaseError)
                else "invalid_handle"
                if isinstance(error, ClusterError)
                else "database_unavailable"
            )
            raise DatabaseError(code) from None
        with self._condition:
            self._raw[raw] = role
            raw._desktop_source = self
            self._connecting[role] -= 1
        try:
            self._usable()
            verify(raw, self)
            self._usable()
            return raw
        except BaseException as error:
            # This raw was never handed to caller. Close once and let the close
            # wrapper retain its strong registration if native finish is unknown.
            raw.close()
            if isinstance(error, DatabaseError):
                raise error from None
            state = getattr(error, "sqlstate", None)
            code = (
                "database_mismatch"
                if type(state) is str and state.startswith("42")
                else "database_unavailable"
            )
            raise DatabaseError(code) from None

    def _engine(self, role):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        self._usable()
        return create_engine(
            "postgresql+psycopg://",
            creator=lambda: self._connect(role),
            poolclass=NullPool,
            hide_parameters=True,
            echo=False,
            echo_pool=False,
        )

    def document_runtime(self):
        from ara.documents.runtime import DocumentRuntime

        self._usable()
        with self._condition:
            self._open()
            if self._document is None:
                self._document = DocumentRuntime(
                    engine=self._engine("document"),
                    user_id=self._identity.user_id,
                    project_id=self._identity.project_id,
                    mode="local",
                )
            return self._document

    def settings(self):
        self._usable()
        return DesktopDatabaseSettings(self)

    def view(self):
        self._origin()
        with self._condition:
            phase = (
                "failed"
                if self._uncertain
                else "closed"
                if self._closed
                else "stopping"
                if self._stopping
                else "ready"
            )
            return DatabaseView(
                phase,
                "cleanup_unknown" if self._uncertain else None,
                len(self._raw),
                sum(self._connecting.values()),
                not self._closed,
            )

    def shutdown(self, timeout=5):
        self._origin()
        require(
            type(timeout) in (int, float) and 0 <= timeout <= 5 and math.isfinite(timeout),
            "validation_error",
        )
        end = time.monotonic() + timeout
        with self._condition:
            self._stopping = True
            self._finish()
            while not self._closed and not self._uncertain:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._closed


def bind_database(home, cluster, *, schema):
    from ara.desktop.data_home import DataHome
    from ara.desktop.postgres_cluster import ClusterRuntime
    from ara.desktop.postgres_schema import SchemaPreparation

    global _PID

    require(
        type(home) is DataHome
        and type(cluster) is ClusterRuntime
        and type(schema) is SchemaPreparation,
        "validation_error",
    )
    pid = os.getpid()
    require(_PID is None or _PID == pid)
    try:
        identity, physical, receipt = home.identity(), cluster.identity(), schema.receipt()
        require(
            (
                identity.installation_id,
                identity.user_id,
                identity.project_id,
                physical.system_identifier,
                physical.database_oid,
            )
            == (
                receipt.installation_id,
                receipt.user_id,
                receipt.project_id,
                receipt.system_identifier,
                receipt.database_oid,
            )
        )
        require(identity.installation_id == physical.installation_id)
    except Exception:
        raise DatabaseError("invalid_handle") from None
    with _LOCK:
        require(home not in _REGISTRY, "database_busy")
        source = DatabaseSource(_KEY, home, cluster, schema, receipt)
        _REGISTRY[home], _PID = source, pid
        return source
