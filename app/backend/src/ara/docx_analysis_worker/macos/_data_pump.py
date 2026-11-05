"""One bounded nonblocking data thread; control has its own independent mutex."""

import os
import select
import threading

from ..wire import StreamDecoder
from ._bootstrap import TokenReader
from ._driver_models import AttemptView


class DataPump:
    def __init__(self, holder, control, binding, spec_sha, frame, clock):
        self.holder, self.control, self.clock = holder, control, clock
        self._frame, self._offset = frame, 0
        self._fds = {name: getattr(holder, name + "_fd") for name in ("armed", "events", "status")}
        self._request_fd = holder.request_fd
        self._eof = set()
        self._armed = TokenReader("armed")
        self._events = StreamDecoder(
            binding, lane="events", expected_execution_spec_sha256=spec_sha
        )
        self._status_decoder = StreamDecoder(binding, lane="status")
        self._status = self._terminal = None
        self._bad_events = self._bad_status = False
        self._candidate = None
        self._stage = None
        self._phase = "starting"
        self._cleanup = False
        self._exit_kind = self._exit_code = None
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, name="aira-fixture-data", daemon=True)

    def view(self):
        stopped, error, _, _ = self.control.flags()
        with self._lock:
            return AttemptView(
                self._phase,
                self._stage,
                stopped,
                error,
                self._exit_kind,
                self._exit_code,
                self._cleanup,
                self._candidate is not None and not (stopped or error),
            )

    def candidate(self):
        if not self.control.check():
            return None
        with self._lock:
            return self._candidate

    def discard(self):
        with self._lock:
            self._candidate = self._frame = None

    def _close_request(self):
        self._frame = None
        self.holder.close_request()

    def _read(self, name):
        data = os.read(self._fds[name], 65536)
        if not data:
            self._eof.add(name)
        if name == "armed":
            if data:
                self._armed.feed(data)
            else:
                self._armed.finish()
                with self._lock:
                    self._phase = "running"
        elif name == "events":
            if self._bad_events:
                return
            if data:
                for message in self._events.feed(data):
                    if message.kind == "stage":
                        with self._lock:
                            self._stage = message.values["stage"]
                    elif message.kind in ("result", "error"):
                        self._terminal = message.kind
                        if message.kind == "result":
                            # Private until all OS/EOF/time gates have passed.
                            self._reply = message.payload
            elif not self.control.stop_requested:
                self._events.finish()
        elif name == "status":
            if self._bad_status:
                return
            if data:
                for message in self._status_decoder.feed(data):
                    self._status = message
            else:
                self._status_decoder.finish()

    def run(self):
        exit_seen = None
        self._reply = None
        try:
            while True:
                live = self.control.check()
                try:
                    now = self.clock.now_ns()
                except Exception:
                    now = None
                    self.control.abort("clock")
                if not live:
                    if self._frame is not None:
                        self._close_request()
                    with self._lock:
                        self._phase = "stopping"
                code = self.holder.process.poll()
                if code is not None:
                    if exit_seen is None:
                        exit_seen = now
                    if code != 0:
                        self.control.abort("process")
                if self._status is not None and exit_seen is None:
                    exit_seen = now
                if code is not None and self._eof == {"armed", "events", "status"}:
                    break
                if code is not None and (
                    now is None
                    or exit_seen is None
                    or now >= exit_seen + 2_000_000_000
                    or (not live)
                ):
                    self.control.abort("protocol")
                    break
                readers = [fd for name, fd in self._fds.items() if name not in self._eof]
                writers = (
                    [self._request_fd]
                    if self._armed.ready and live and self._frame is not None
                    else []
                )
                ready_r, ready_w, _ = select.select(readers, writers, [], 0.1)
                for name, fd in self._fds.items():
                    if fd not in ready_r:
                        continue
                    try:
                        self._read(name)
                    except BlockingIOError:
                        pass
                    except Exception:
                        self.control.abort("protocol")
                        if name == "events":
                            self._bad_events = True
                        elif name == "status":
                            self._bad_status = True
                        else:
                            self._eof.add(name)
                if ready_w and self.control.check() and self._frame is not None:
                    try:
                        count = os.write(
                            self._request_fd, self._frame[self._offset : self._offset + 65536]
                        )
                        if count <= 0:
                            raise OSError()
                        self._offset += count
                        if self._offset == len(self._frame):
                            self._close_request()
                    except BlockingIOError:
                        pass
                    except Exception:
                        self.control.abort("transport")
                        self._close_request()
            status = self._status
            code = self.holder.process.poll()
            proof = (
                status is not None
                and not self._bad_status
                and "status" in self._eof
                and code == 0
                and status.values["cleanup_confirmed"]
            )
            clean = (
                proof and status.values["exit_kind"] == "clean" and status.values["exit_code"] == 0
            )
            valid = (
                clean
                and self._terminal == "result"
                and not self._bad_events
                and self._eof == {"armed", "events", "status"}
                and self._armed.ready
            )
            if not valid and not self.control.stop_requested:
                self.control.abort("process")
            live = self.control.check()
            with self._lock:
                self._cleanup = bool(proof)
                self._exit_kind = status.values["exit_kind"] if status else None
                self._exit_code = status.values["exit_code"] if status else None
                self._phase = "closed" if proof else "blocked"
                if valid and live:
                    self._candidate = self._reply
        except BaseException:
            self.control.abort("transport")
            with self._lock:
                self._phase = "blocked"
        finally:
            self._frame = self._reply = None
            self._events = self._status_decoder = None
            # Never release the caller's slot or manufacture child exit evidence.
            self.control.finish()
