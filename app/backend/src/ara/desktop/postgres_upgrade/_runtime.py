"""Owned bounded upgrade; unknown outcomes retain the shared migration claim."""

import math
import os
import threading

from ara.desktop import _migration_gate

from ._models import (
    SOURCE,
    TARGET,
    UpgradeError,
    UpgradeLimits,
    UpgradeTools,
    UpgradeView,
    mapped,
    require,
)


class UpgradePreparation:
    def __init__(self, home, cluster, *, migrations, tools, limits=None, target_revision=TARGET):
        from ara.desktop.data_home import DataHome
        from ara.desktop.postgres_cluster import ClusterRuntime
        from ara.desktop.postgres_cluster._models import checked_path

        require(type(home) is DataHome and type(cluster) is ClusterRuntime, "validation_error")
        try:
            checked_path(migrations)
        except Exception:
            raise UpgradeError("validation_error") from None
        try:
            require(
                home.identity().installation_id == cluster.identity().installation_id,
                "invalid_handle",
            )
        except Exception:
            raise UpgradeError("invalid_handle") from None
        require(type(tools) is UpgradeTools, "validation_error")
        require(tools.dump.parent == cluster._tools.postgres.parent, "validation_error")
        require(limits is None or type(limits) is UpgradeLimits, "validation_error")
        require(
            type(target_revision) is str and target_revision in (TARGET, "0014_docx_file_states"),
            "validation_error",
        )
        self._revision = target_revision
        self._source = SOURCE if target_revision == TARGET else TARGET
        self._tools, self._limits = tools, limits or UpgradeLimits()
        self._home, self._cluster, self._migrations = home, cluster, migrations
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._phase, self._error = "new", None
        self._started = self._pending = self._uncertain = False
        self._settled = self._thread_started = False
        self._thread = self._backend = self._result = None

    def __repr__(self):
        return "<local upgrade preparation>"

    def __copy__(self):
        raise TypeError("process-local upgrade preparation")

    def __deepcopy__(self, memo):
        raise TypeError("process-local upgrade preparation")

    def __reduce_ex__(self, protocol):
        raise TypeError("process-local upgrade preparation")

    def _origin(self):
        require(
            type(self) is UpgradePreparation and getattr(self, "_pid", None) == os.getpid(),
            "invalid_handle",
        )

    def _view(self):
        return UpgradeView(
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
            require(_migration_gate.claim(self), "upgrade_busy")
            self._started = self._pending = True
            self._phase = "preparing"
        try:
            thread = threading.Thread(target=self._work, name="aira-pg-upgrade", daemon=True)
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
        from ._backend import Backend, Stopped

        error, result = None, None
        try:
            self._backend = Backend(self)
            result = self._backend.run()
        except Stopped:
            pass
        except BaseException as failure:
            error = mapped(failure)
        with self._lock:
            self._error = self._error or error
            self._phase = "failed" if self._error else "stopping"
        try:
            clean = self._backend is None or self._backend.close()
        except BaseException:
            clean = False
        if clean and result is not None:
            # Cleanup itself may span suspension or a concurrent Stop. The
            # durable receipt remains usable on retry, but this attempt must
            # still be admitted when it publishes success to its caller.
            try:
                self._backend.check()
            except Stopped:
                result = None
            except BaseException as failure:
                error = error or mapped(failure)
        with self._lock:
            self._error = self._error or error
            self._uncertain |= not clean
            self._pending = self._uncertain
            if not clean:
                self._error = self._error or "cleanup_unknown"
            self._result = result if clean and self._error is None else None
            self._phase = (
                "failed"
                if self._error
                else ("ready" if self._result.backup_id is not None else "not_needed")
                if self._result is not None
                else "closed"
            )
        self._release()

    def shutdown(self, timeout=5):
        self._origin()
        require(
            type(timeout) in (int, float) and 0 <= timeout <= 5 and math.isfinite(timeout),
            "validation_error",
        )
        with self._lock:
            if self._phase == "new":
                self._phase = "closed"
                return True
            self._stop.set()
            if self._phase in ("preparing", "backing_up", "migrating", "publishing"):
                self._phase = "stopping"
            thread = self._thread if self._thread_started else None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.view().resources_pending

    def result(self):
        self._origin()
        with self._lock:
            require(
                self._phase in ("ready", "not_needed") and not self._view().resources_pending,
                "invalid_handle",
            )
            try:
                require(
                    self._home.identity().installation_id == self._result.installation_id
                    and self._cluster.identity() == self._backend.identity,
                    "invalid_handle",
                )
            except Exception:
                raise UpgradeError("invalid_handle") from None
            return self._result

    def backup_path(self):
        result = self.result()
        require(result.backup_id is not None, "invalid_handle")
        return self._home.path("backups") / "postgres" / str(result.backup_id) / "data.dump"
