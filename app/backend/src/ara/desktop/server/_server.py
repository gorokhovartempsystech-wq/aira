"""Explicit socket/server setup. Uvicorn never owns the application lifespan."""

import socket
import sys

from ._models import HostError, error_reply


def prepare_socket(sock):
    sock.set_inheritable(False)
    if sys.platform == "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", 0))


class ShutdownFence:
    def __init__(self, application, stop):
        self.application, self.stop = application, stop

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.stop.is_set():
            await error_reply(send, HostError("server_stopping"))
            return
        await self.application(scope, receive, send)


def make_server(application, port):
    import uvicorn

    class DrainingServer(uvicorn.Server):
        drained = False

        async def shutdown(self, sockets=None):
            await super().shutdown(sockets=sockets)
            self.drained = True

    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        loop="asyncio",
        http="h11",
        ws="none",
        lifespan="off",
        proxy_headers=False,
        access_log=False,
        workers=1,
        reload=False,
        log_config=None,
        log_level="critical",
        use_colors=False,
        server_header=False,
        date_header=False,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=None,
        limit_concurrency=16,
        backlog=32,
    )
    return DrainingServer(config)
