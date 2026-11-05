"""Strict same-loop ASGI lifespan ownership, with no cancellation of cleanup."""

import asyncio

from ._models import require


class LifespanSession:
    def __init__(self, application):
        self.application = application
        self.state = {}
        self.queue = asyncio.Queue(maxsize=1)
        self.task = None
        self.received = None
        self.startup_complete = self.startup_failed = False
        self.shutdown_complete = self.shutdown_failed = False
        self.shutdown_requested = self.failed = False

    @property
    def done(self):
        return self.task is not None and self.task.done()

    @property
    def clean(self):
        return self.done and self.shutdown_complete and not self.failed

    def begin(self):
        require(self.task is None, "lifespan_error")
        self.queue.put_nowait({"type": "lifespan.startup"})
        self.task = asyncio.create_task(self._main(), name="aira-app-lifespan")

    async def receive(self):
        message = await self.queue.get()
        self.received = message["type"]
        return message

    async def send(self, message):
        try:
            require(type(message) is dict, "lifespan_error")
            kind = message.get("type")
            if kind in {"lifespan.startup.complete", "lifespan.startup.failed"}:
                require(
                    self.received == "lifespan.startup"
                    and not self.startup_complete
                    and not self.startup_failed
                    and not self.failed,
                    "lifespan_error",
                )
                self.startup_complete = kind.endswith("complete")
                self.startup_failed = not self.startup_complete
                self.failed = self.startup_failed
            else:
                require(
                    kind in {"lifespan.shutdown.complete", "lifespan.shutdown.failed"}
                    and self.received == "lifespan.shutdown"
                    and self.startup_complete
                    and not self.shutdown_complete
                    and not self.shutdown_failed
                    and not self.failed,
                    "lifespan_error",
                )
                self.shutdown_complete = kind.endswith("complete")
                self.shutdown_failed = not self.shutdown_complete
                self.failed = self.shutdown_failed
        except BaseException:
            self.failed = True
            raise

    async def _main(self):
        try:
            await self.application(
                dict(
                    type="lifespan",
                    asgi={"version": "3.0", "spec_version": "2.0"},
                    state=self.state,
                ),
                self.receive,
                self.send,
            )
        except BaseException:
            self.failed = True
        finally:
            if not (self.startup_failed or self.shutdown_complete or self.shutdown_failed):
                self.failed = True

    async def close(self):
        if self.startup_complete and not self.done and not self.shutdown_requested:
            self.shutdown_requested = True
            await self.queue.put({"type": "lifespan.shutdown"})
        # This may outlive the caller's shutdown timeout; it still belongs to this loop.
        if self.task is not None:
            await self.task
        return self.clean
