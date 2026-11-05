"""One explicit loopback owner, retaining work through caller shutdown deadlines."""

import asyncio
import math
import os
import socket
import threading
from dataclasses import replace

from ara.desktop.access import LicensedApplication, new_session_token
from ara.licensing.client import LicenseClient

from . import _registry
from ._body import BodyEnvelope
from ._lifecycle import LifespanSession
from ._models import HostView, LocalConnection, fail, require
from ._server import ShutdownFence, make_server, prepare_socket

STARTUP_TIMEOUT = 15.0


class LoopbackServer:
    def __init__(self, application, license_client):
        require(callable(application) and type(license_client) is LicenseClient)
        self._application, self._client = application, license_client
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = self._socket = self._connection = None
        self._launch_pending = False
        self._phase, self._error, self._clean = "new", None, False

    def _owner(self):
        require(getattr(self, "_pid", None) == os.getpid(), "invalid_handle")

    def __copy__(self):
        fail("invalid_handle")

    def __deepcopy__(self, memo):
        fail("invalid_handle")

    def __reduce_ex__(self, protocol):
        fail("invalid_handle")

    def _view_locked(self):
        pending = (
            self._launch_pending
            or self._socket is not None
            or (self._thread is not None and self._thread.is_alive())
        )
        phase = "stopping" if self._phase == "closed" and pending else self._phase
        return HostView(phase, self._error, bool(pending), self._clean and not pending)

    def view(self):
        self._owner()
        with self._lock:
            return self._view_locked()

    def connection(self):
        self._owner()
        with self._lock:
            if self._phase == "ready" and not self._stop.is_set():
                return replace(self._connection)
            return None

    def start(self):
        self._owner()
        with self._lock:
            if self._phase != "new":
                return self._view_locked()
            _registry.claim(self, self._application, self._client)
            try:
                require(self._client.view().phase == "new")
            except BaseException:
                _registry.release(self)
                fail("validation_error")
            self._phase, self._launch_pending = "starting", True
            initial = self._view_locked()
        # Thread creation and all runtime I/O are outside the metadata mutex.
        thread = None
        try:
            thread = threading.Thread(target=self._work, name="aira-loopback-server", daemon=True)
            with self._lock:
                self._thread = thread
            thread.start()
        except BaseException:
            self._failed("server_error")
            if thread is None or not thread.is_alive():
                self._finish(True)
        finally:
            with self._lock:
                self._launch_pending = False
        return initial

    def shutdown(self, *, timeout=5):
        self._owner()
        require(type(timeout) in {int, float} and 0 <= timeout <= 5 and math.isfinite(timeout))
        with self._lock:
            if self._phase == "new":
                self._phase, self._clean = "closed", True
            elif self._phase not in {"closed", "failed"}:
                self._phase = "stopping"
            self._stop.set()
            self._connection = None
            thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        return self.view().clean_shutdown

    def _failed(self, code):
        self._stop.set()
        with self._lock:
            if self._error is None or code == "lifespan_error":
                self._error = code
            self._phase, self._connection = "failed", None

    def _finish(self, clean):
        # Called only by the worker, or after a failed launch with no live worker.
        try:
            self._client.close()
        except BaseException:
            clean = False
            self._failed("server_error")
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except BaseException:
                clean = False
                self._failed("server_error")
            else:
                with self._lock:
                    self._socket = None
        if clean:
            _registry.release(self)
        with self._lock:
            self._connection, self._clean = None, clean
            self._phase = "failed" if self._error is not None else "closed"

    def _work(self):
        clean = False
        try:
            self._client.start()
            clean = asyncio.run(self._run())
        except BaseException:
            self._failed("server_error")
        finally:
            self._finish(clean)

    async def _run(self):
        life = None
        drain_clean = True
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            with self._lock:
                self._socket = sock
            prepare_socket(sock)
            port = sock.getsockname()[1]
            connection = LocalConnection(f"http://127.0.0.1:{port}", new_session_token())
            life = LifespanSession(self._application)
            life.begin()
            deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT
            while not (life.startup_complete or life.failed or life.done):
                if not self._stop.is_set() and asyncio.get_running_loop().time() >= deadline:
                    self._failed("startup_timeout")
                await asyncio.sleep(0.005)
            if life.failed:
                self._failed("lifespan_error")
            if life.startup_complete and not self._stop.is_set():
                body = BodyEnvelope(self._application, life.state)
                access = LicensedApplication(
                    body,
                    self._client,
                    origin=connection.origin,
                    session_token=connection.session_token,
                )
                server = make_server(ShutdownFence(access, self._stop), port)
                drain_clean = await self._serve(server, sock, life, connection)
        except BaseException:
            self._failed("server_error")
        finally:
            if life is not None:
                # Neither a startup deadline nor a caller's join deadline cancels this task.
                clean = await life.close()
                if not clean:
                    self._failed("lifespan_error")
                drain_clean = drain_clean and clean
        return drain_clean

    async def _serve(self, server, sock, life, connection):
        async def serving():
            try:
                await server.serve(sockets=[sock])
                return True
            except BaseException:
                # Catch SystemExit inside the task, before asyncio can abort the loop.
                self._failed("server_error")
                return False

        task = asyncio.create_task(serving(), name="aira-loopback-http")
        clean = True
        try:
            while not task.done():
                if life.failed or life.done:
                    self._failed("lifespan_error")
                if self._stop.is_set():
                    server.should_exit = True
                elif server.started:
                    with self._lock:
                        if not self._stop.is_set():
                            self._connection, self._phase = connection, "ready"
                await asyncio.sleep(0.005)
            clean = await task
            if not self._stop.is_set():
                self._failed("server_error")
        finally:
            if hasattr(server, "servers") and not server.drained:
                try:
                    await server.shutdown(sockets=[sock])
                except BaseException:
                    clean = False
                    self._failed("server_error")
                    # Retain accepted tasks if the library's drain itself fails. Closing
                    # application resources while those tasks write would be unsafe.
                    for listener in server.servers:
                        listener.close()
                    for connection in tuple(server.server_state.connections):
                        connection.shutdown()
                    while server.server_state.tasks:
                        await asyncio.gather(
                            *tuple(server.server_state.tasks), return_exceptions=True
                        )
        return clean
