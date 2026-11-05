"""Programmatic fixture desktop lifecycle, independent of a future GUI/installer."""

import os
import sys
import threading
import time

from . import _registry
from ._models import DesktopError, DesktopView, FixtureConfig, Stopped, budget, require


class FixtureDesktop:
    def __init__(self, config):
        require(type(config) is FixtureConfig)
        self._config, self._pid = config, os.getpid()
        self._lock = threading.Lock()
        self._stop, self._launch_done = threading.Event(), threading.Event()
        self._launch_done.set()
        self._phase, self._stage, self._error = "new", None, None
        self._pending = self._launch_pending = self._unknown = self._thread_started = False
        self._thread = self._session = None

    def __repr__(self):
        return "<FixtureDesktop>"

    def _origin(self):
        require(
            type(self) is FixtureDesktop and getattr(self, "_pid", None) == os.getpid(),
            "invalid_handle",
        )

    def __copy__(self):
        raise TypeError("process-local fixture desktop")

    def __deepcopy__(self, memo):
        raise TypeError("process-local fixture desktop")

    def __reduce_ex__(self, protocol):
        raise TypeError("process-local fixture desktop")

    def _view(self):
        return DesktopView(
            self._phase,
            self._stage,
            self._error,
            bool(
                self._pending
                or self._unknown
                or self._launch_pending
                or (self._thread_started and self._thread.is_alive())
            ),
        )

    def view(self):
        self._origin()
        with self._lock:
            return self._view()

    def connection(self):
        self._origin()
        with self._lock:
            if self._phase != "ready" or self._stop.is_set():
                return None
            session = self._session
        value = session.connection()
        with self._lock:
            return value if self._phase == "ready" and not self._stop.is_set() else None

    def start(self):
        self._origin()
        with self._lock:
            if self._phase != "new":
                return self._view()
            require(sys.platform == "darwin", "platform_unavailable")
            _registry.claim(self)
            self._phase = "starting"
            self._pending = self._launch_pending = True
            self._launch_done.clear()
        try:
            thread = threading.Thread(target=self._work, name="aira-fixture-desktop", daemon=True)
            with self._lock:
                self._thread = thread
            thread.start()
        except BaseException:
            with self._lock:
                self._unknown = True
                self._phase, self._error = "failed", "cleanup_unknown"
                self._stop.set()
        else:
            with self._lock:
                self._thread_started = True
        finally:
            with self._lock:
                self._launch_pending = False
                self._launch_done.set()
        return self.view()

    def _stage_at(self, stage):
        with self._lock:
            self._stage = stage

    def _failed(self, code):
        with self._lock:
            self._phase = "failed"
            self._error = self._error or code
            self._stop.set()

    def _work(self):
        self._launch_done.wait()
        with self._lock:
            if self._unknown:
                return
        clean, was_ready = False, False
        try:
            from ._wiring import Session

            self._session = Session(self)
            self._session.start()
            with self._lock:
                if not self._stop.is_set():
                    self._phase, self._stage = "ready", "running"
                    was_ready = True
            while not self._stop.wait(0.05):
                if not self._session.healthy():
                    raise DesktopError("runtime_failed")
        except BaseException as failure:
            # Stopped is internal, carries no user/native data, and is not a failure.
            if not isinstance(failure, Stopped):
                code = (
                    failure.code
                    if isinstance(failure, DesktopError)
                    else "runtime_failed"
                    if was_ready
                    else "startup_failed"
                )
                self._failed(code)
        finally:
            self._stage_at("cleanup")
            try:
                clean = self._session is None or self._session.close()
            except BaseException:
                clean = False
            with self._lock:
                self._unknown |= not clean
                self._pending = not clean
                if not clean:
                    self._error = self._error or "cleanup_unknown"
                self._phase = "failed" if self._error else "closed"
            if clean:
                _registry.release(self)

    def shutdown(self, timeout=5):
        self._origin()
        budget(timeout)
        end = time.monotonic() + timeout
        with self._lock:
            self._stop.set()
            if self._phase == "new":
                self._phase = "closed"
            elif self._phase not in ("closed", "failed"):
                self._phase = "stopping"
        self._launch_done.wait(max(0, end - time.monotonic()))
        with self._lock:
            thread = self._thread if self._thread_started else None
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0, end - time.monotonic()))
        return not self.view().resources_pending
