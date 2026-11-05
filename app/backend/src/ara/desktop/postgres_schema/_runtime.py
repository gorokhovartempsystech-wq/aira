"""One process-wide schema job: Alembic's context proxy is process-global."""

import math
import os
import threading

from ara.desktop import _migration_gate

from ._models import SchemaError, SchemaView, require


class SchemaPreparation:
    def __init__(self, home, cluster, *, migrations):
        from ara.desktop.data_home import DataHome
        from ara.desktop.postgres_cluster import ClusterRuntime
        from ara.desktop.postgres_cluster._models import checked_path

        require(type(home) is DataHome and type(cluster) is ClusterRuntime, "validation_error")
        try:
            checked_path(migrations)
        except Exception:
            raise SchemaError("validation_error") from None
        try:
            require(
                home.identity().installation_id == cluster.identity().installation_id,
                "invalid_handle",
            )
        except Exception:
            raise SchemaError("invalid_handle") from None
        self._home, self._cluster, self._migrations = home, cluster, migrations
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._phase, self._error = "new", None
        self._started = self._pending = self._uncertain = False
        self._settled = self._thread_started = False
        self._thread = self._backend = self._receipt = None

    def __repr__(self):
        return "<local schema preparation>"

    def __copy__(self):
        raise TypeError("process-local schema preparation")

    def __deepcopy__(self, memo):
        raise TypeError("process-local schema preparation")

    def __reduce_ex__(self, protocol):
        raise TypeError("process-local schema preparation")

    def _origin(self):
        require(
            type(self) is SchemaPreparation and getattr(self, "_pid", None) == os.getpid(),
            "invalid_handle",
        )

    def _view(self):
        return SchemaView(
            self._phase,
            self._error,
            self._pending
            or self._uncertain
            or (self._thread is not None and self._thread.is_alive())
            or (self._started and not self._settled),
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
            require(_migration_gate.claim(self), "schema_busy")
            self._started = self._pending = True
            self._phase = "preparing"
        try:
            thread = threading.Thread(target=self._work, name="aira-pg-schema", daemon=True)
            with self._lock:
                self._thread = thread
            thread.start()
        except BaseException:
            with self._lock:
                self._uncertain = self._settled = True
                self._phase, self._error = "failed", "cleanup_unknown"
                self._stop.set()
        else:
            with self._lock:
                self._settled = self._thread_started = True
        self._release()
        return self.view()

    def _release(self):
        with self._lock:
            if not self._settled or self._pending or self._uncertain:
                return
            _migration_gate.release(self)

    def _work(self):
        from ara.desktop.postgres_cluster import ClusterError

        from ._backend import Backend, Stopped

        error, receipt = None, None
        try:
            self._backend = Backend(self)
            receipt = self._backend.run()
        except Stopped:
            pass
        except SchemaError as failure:
            error = failure.code
        except ClusterError as failure:
            error = (
                "cleanup_unknown"
                if failure.code == "cleanup_unknown"
                else "schema_recovery_required"
            )
        except BaseException as failure:
            state = getattr(getattr(failure, "orig", failure), "sqlstate", None)
            error = (
                "schema_recovery_required"
                if type(state) is str and state.startswith("42")
                else "schema_unavailable"
            )
        with self._lock:
            self._error = self._error or error
            self._phase = "failed" if self._error else "stopping"
        try:
            clean = self._backend is None or self._backend.close()
        except BaseException:
            clean = False
        if clean and receipt is not None:
            # Cleanup itself may span suspension or a concurrent Stop. The
            # durable receipt remains usable on retry, but this attempt must
            # still be admitted when it publishes success to its caller.
            try:
                self._backend.check()
            except Stopped:
                receipt = None
            except SchemaError as failure:
                error = error or failure.code
            except BaseException:
                error = error or "schema_unavailable"
        with self._lock:
            self._error = self._error or error
            self._uncertain |= not clean
            self._pending = self._uncertain
            if not clean:
                self._error = self._error or "cleanup_unknown"
            self._receipt = receipt if clean and self._error is None else None
            self._phase = (
                "failed" if self._error else "ready" if self._receipt is not None else "closed"
            )
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
            if self._phase == "preparing":
                self._phase = "stopping"
            thread = self._thread if self._thread_started else None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.view().resources_pending

    def receipt(self):
        self._origin()
        with self._lock:
            require(self._phase == "ready" and not self._view().resources_pending, "invalid_handle")
            try:
                require(
                    self._home.identity().installation_id == self._receipt.installation_id
                    and self._cluster.identity() == self._backend.identity,
                    "invalid_handle",
                )
            except Exception:
                raise SchemaError("invalid_handle") from None
            return self._receipt
