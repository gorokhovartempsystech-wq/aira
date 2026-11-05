"""Process-local cluster handle; worker owns all IO and graceful teardown."""

import math
import os
import threading
from types import MappingProxyType

from ._models import ClusterError, ClusterView, PgTools, require

_REGISTRY = {}
_REGISTRY_LOCK = threading.Lock()


class ClusterRuntime:
    def __init__(self, home, tools):
        from ara.desktop.data_home import DataHome

        require(type(home) is DataHome and type(tools) is PgTools, "validation_error")
        try:
            home.identity()
            PgTools(tools.target, tools.postgres, tools.initdb, tools.control)
        except Exception:
            raise ClusterError("invalid_handle") from None
        self._home, self._tools = home, tools
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._phase, self._error = "new", None
        self._started = self._pending = self._uncertain = False
        self._start_settled = self._thread_started = False
        self._thread = self._backend = self._identity = self._plan = None

    def __repr__(self):
        return "<local PostgreSQL cluster>"

    def __copy__(self):
        raise TypeError("process-local cluster")

    def __deepcopy__(self, memo):
        raise TypeError("process-local cluster")

    def __reduce_ex__(self, protocol):
        raise TypeError("process-local cluster")

    def _origin(self):
        require(
            type(self) is ClusterRuntime and getattr(self, "_pid", None) == os.getpid(),
            "invalid_handle",
        )

    def _view(self):
        alive = self._thread is not None and self._thread.is_alive()
        return ClusterView(
            self._phase,
            self._error,
            self._pending
            or self._uncertain
            or alive
            or (self._started and not self._start_settled),
        )

    def view(self):
        self._origin()
        with self._lock:
            return self._view()

    def start(self):
        self._origin()
        with self._lock:
            if self._phase != "new":
                require(self._started, "invalid_handle")
                return self._view()
            with _REGISTRY_LOCK:
                require(self._home not in _REGISTRY, "cluster_busy")
                _REGISTRY[self._home] = self
            self._started = self._pending = True
            self._phase = "preparing"
        try:
            thread = threading.Thread(target=self._work, name="aira-pg-cluster", daemon=True)
            with self._lock:
                self._thread = thread
            thread.start()
        except BaseException:
            with self._lock:
                self._uncertain = True
                self._phase, self._error = "failed", "cleanup_unknown"
                self._start_settled = True
                self._stop.set()
        else:
            with self._lock:
                self._thread_started = self._start_settled = True
        self._release()
        return self.view()

    def _release(self):
        with self._lock:
            if not self._start_settled or self._pending or self._uncertain:
                return
            with _REGISTRY_LOCK:
                if _REGISTRY.get(self._home) is self:
                    del _REGISTRY[self._home]

    def _phase_to(self, phase):
        with self._lock:
            if not self._stop.is_set() and self._error is None:
                self._phase = phase

    def _ready(self, identity, plan):
        with self._lock:
            if not self._stop.is_set() and self._error is None:
                self._identity, self._plan = identity, plan
                self._phase = "ready"

    def _work(self):
        from ._backend import Backend, Stopped

        error = None
        try:
            self._backend = Backend(self)
            self._backend.run()
        except Stopped:
            pass
        except ClusterError as failure:
            error = failure.code
        except BaseException:
            error = "cluster_unavailable"
        with self._lock:
            self._error = self._error or error
            self._phase = "failed" if self._error else "stopping"
        try:
            clean = self._backend is None or self._backend.close()
        except BaseException:
            clean = False
        with self._lock:
            self._uncertain |= not clean
            self._pending = self._uncertain
            if not clean:
                self._error = self._error or "cleanup_unknown"
            self._phase = "failed" if self._error else "closed"
        self._release()

    def shutdown(self, timeout=5):
        self._origin()
        require(
            type(timeout) in (int, float) and math.isfinite(timeout) and 0 <= timeout <= 5,
            "validation_error",
        )
        with self._lock:
            if self._phase == "new":
                self._phase = "closed"
                return True
            self._stop.set()
            if self._phase not in ("closed", "failed"):
                self._phase = "stopping"
            thread = self._thread if self._thread_started else None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.view().resources_pending

    def _require_ready(self):
        require(
            self._phase == "ready"
            and not self._stop.is_set()
            and self._home.view().phase == "open"
            and self._backend is not None
            and self._backend.command is not None
            and self._backend.command.view().phase == "running",
            "invalid_handle",
        )

    def connection(self, database="aira"):
        self._origin()
        require(type(database) is str and database in ("aira", "postgres"), "validation_error")
        with self._lock:
            self._require_ready()
            return MappingProxyType(dict(self._plan.connection(database)))

    def identity(self):
        self._origin()
        with self._lock:
            self._require_ready()
            return self._identity
