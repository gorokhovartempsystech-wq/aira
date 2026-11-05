"""One thread owns native handles; callers only request Stop and observe state."""

import math
import os
import sys
import threading

from ._models import CommandError, ProcessView, require
from ._wire import bootstrap

_REGISTRY = {}
_REGISTRY_LOCK = threading.Lock()


class OwnedCommand:
    def __init__(self, owner, executable, arguments, *, cwd, capture_stdout=False):
        from ara.docx_analysis_worker.macos import RuntimeOwner

        require(type(owner) is RuntimeOwner, "invalid_handle")
        try:
            owner._check_origin()
        except Exception:
            raise CommandError("invalid_handle") from None
        payload = bootstrap(executable, arguments, cwd, capture_stdout)
        self._owner, self._payload, self._capture = owner, payload, capture_stdout
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._phase, self._error, self._returncode = "new", None, None
        self._pending = self._uncertain = self._started = self._thread_started = False
        self._start_settled = False
        self._thread = self._backend = None
        self._output = b""

    def __repr__(self):
        return "<owned PostgreSQL command>"

    def __copy__(self):
        raise TypeError("process-local command")

    def __deepcopy__(self, memo):
        raise TypeError("process-local command")

    def __reduce_ex__(self, protocol):
        raise TypeError("process-local command")

    def _origin(self):
        require(
            type(self) is OwnedCommand and getattr(self, "_pid", None) == os.getpid(),
            "invalid_handle",
        )

    def _view(self):
        alive = self._thread is not None and self._thread.is_alive()
        return ProcessView(
            self._phase,
            self._error,
            self._pending
            or self._uncertain
            or alive
            or (self._started and not self._start_settled),
            self._returncode,
        )

    def view(self):
        self._origin()
        with self._lock:
            return self._view()

    def start(self):
        self._origin()
        require(sys.platform == "darwin", "platform_unavailable")
        with self._lock:
            if self._phase != "new":
                require(self._started, "invalid_handle")
                return self._view()
            with _REGISTRY_LOCK:
                require(self._owner not in _REGISTRY, "process_busy")
                _REGISTRY[self._owner] = self
            self._started = self._pending = True
            self._phase = "starting"
        try:
            thread = threading.Thread(target=self._work, name="aira-pg-owner", daemon=True)
            with self._lock:
                self._thread = thread
            thread.start()
        except BaseException:
            self._failure("cleanup_unknown", uncertain=True)
            self._stop.set()
            with self._lock:
                self._start_settled = True
        else:
            with self._lock:
                self._thread_started = True
                self._start_settled = True
        self._release_if_safe()
        return self.view()

    def _release_if_safe(self):
        # A fast worker may finish before Thread.start returns (or raises). Its
        # native cleanup cannot settle the caller's still-unknown startup outcome.
        with self._lock:
            if not self._start_settled or self._pending or self._uncertain:
                return
            with _REGISTRY_LOCK:
                if _REGISTRY.get(self._owner) is self:
                    del _REGISTRY[self._owner]

    def _failure(self, code, *, uncertain=False):
        with self._lock:
            self._error = self._error or code
            self._phase = "failed"
            self._uncertain |= uncertain

    def _running(self):
        with self._lock:
            if self._error is None:
                self._phase = "stopping" if self._stop.is_set() else "running"

    def _work(self):
        try:
            from ._native import Backend

            self._backend = Backend(self)
            code, output, error, clean = self._backend.run()
        except BaseException:
            code, output, error, clean = None, b"", "cleanup_unknown", False
        with self._lock:
            self._returncode = code
            self._output = output if clean and error is None and code == 0 else b""
            self._error = self._error or error
            self._uncertain |= not clean
            self._pending = self._uncertain
            if self._error is None and code not in (None, 0):
                self._error = "process_failed"
            self._phase = "failed" if self._error else "exited"
        self._release_if_safe()

    def shutdown(self, timeout=5):
        self._origin()
        require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 <= timeout <= 5)
        with self._lock:
            if self._phase == "new":
                self._phase = "exited"
                return True
            self._stop.set()
            if self._phase not in ("exited", "failed"):
                self._phase = "stopping"
            thread = self._thread if self._thread_started else None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.view().resources_pending

    def stdout(self):
        self._origin()
        with self._lock:
            require(
                self._capture
                and self._phase == "exited"
                and self._returncode == 0
                and not self._view().resources_pending,
                "invalid_handle",
            )
            return self._output
