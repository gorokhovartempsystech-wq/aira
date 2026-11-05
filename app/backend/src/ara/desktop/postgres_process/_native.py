"""Darwin parent worker. Only this thread touches native command descriptors."""

import os
import select
import subprocess
import sys
import time
from pathlib import Path

from ara.docx_analysis_worker.macos import DarwinClock, MacRuntimeError

from ._models import CommandError
from ._wire import ENVIRONMENT, StatusReader

ENTRY = Path(__file__).with_name("_guardian_entry.py")


class Backend:
    def __init__(self, job):
        self.job = job
        self.slot = self.process = self.control = self.status = None
        self.fds = set()
        self.spawn_attempted = self.waited = self.wait_lost = self.unknown = False
        self.error = self.command_code = None
        self.output = b""
        self.reader = StatusReader()
        self.bad_status = self.eof = False

    def fail(self, code, *, uncertain=False):
        self.error = self.error or code
        self.unknown |= uncertain
        self.job._failure(code, uncertain=uncertain)
        self.job._stop.set()

    def close(self, fd):
        if fd in self.fds:
            self.fds.remove(fd)
            try:
                os.close(fd)
            except BaseException:
                self.fail("cleanup_unknown", uncertain=True)

    def pipe(self):
        pair = os.pipe()
        self.fds.update(pair)
        return pair

    def close_control(self):
        fd, self.control = self.control, None
        self.close(fd)

    def wait(self):
        if self.process is None or self.waited or self.wait_lost:
            return
        try:
            pid, status = os.waitpid(self.process.pid, os.WNOHANG)
            if pid == 0:
                return
            if pid != self.process.pid or not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
                raise ChildProcessError()
            self.process.returncode = os.waitstatus_to_exitcode(status)
            self.waited = True
        except BaseException:
            self.wait_lost = True
            self.fail("cleanup_unknown", uncertain=True)

    def read(self):
        if self.status is None:
            return
        try:
            data = os.read(self.status, 65536)
        except BlockingIOError:
            return
        except OSError:
            self.bad_status = True
            self.fail("protocol_error")
            self.close(self.status)
            self.status = None
            self.eof = True
            return
        if not data:
            self.eof = True
            self.close(self.status)
            self.status = None
            return
        if not self.bad_status:
            try:
                before = self.reader.started
                self.reader.feed(data)
                if not before and self.reader.started:
                    self.job._running()
            except CommandError:
                self.bad_status = True
                self.fail("protocol_error")

    def loop(self, clock, deadline):
        pending = self.job._payload
        while True:
            if not self.reader.started and not self.job._stop.is_set():
                try:
                    if clock.now_ns() >= deadline:
                        self.fail("process_unavailable")
                except BaseException:
                    self.fail("process_unavailable")
            if self.job._stop.is_set():
                self.close_control()
            elif pending and self.control is not None:
                try:
                    count = os.write(self.control, pending)
                    if count <= 0:
                        raise OSError()
                    pending = pending[count:]
                except BlockingIOError:
                    pass
                except OSError:
                    self.fail("process_unavailable")
                    self.close_control()
            self.read()
            self.wait()
            if self.wait_lost or (self.waited and (self.eof or self.unknown)):
                break
            readers = [] if self.status is None else [self.status]
            writers = [self.control] if self.control is not None and pending else []
            select.select(readers, writers, [], 0.05)
        if not self.bad_status:
            try:
                self.reader.finish(cancelled=self.job._stop.is_set())
            except CommandError:
                self.fail("protocol_error")
        if self.reader.result is not None:
            self.command_code, self.output, error, uncertain = self.reader.result
            if error:
                self.fail(error, uncertain=uncertain)
            elif uncertain:
                self.fail("cleanup_unknown", uncertain=True)
            if self.output and not self.job._capture:
                self.fail("protocol_error")
        if self.waited and self.process.returncode != 0:
            self.fail("process_unavailable")

    def release_slot(self):
        if self.slot is None or self.unknown:
            return
        try:
            original, self.slot = self.slot, None
            free = self.job._owner.release_slot(original)
            while not free:
                try:
                    probe = self.job._owner.reserve_slot()
                except MacRuntimeError as error:
                    if error.code != "runtime_busy":
                        raise
                    time.sleep(0.05)
                    continue
                free = self.job._owner.release_slot(probe)
        except BaseException:
            self.fail("cleanup_unknown", uncertain=True)

    def run(self):
        try:
            try:
                self.slot = self.job._owner.reserve_slot()
            except MacRuntimeError as error:
                if error.code in ("runtime_busy", "invalid_handle"):
                    self.fail("process_busy" if error.code == "runtime_busy" else "invalid_handle")
                else:
                    self.fail("cleanup_unknown", uncertain=True)
                return None, b"", self.error, not self.unknown
            clock = DarwinClock()
            deadline = clock.now_ns() + 15_000_000_000
            control_r, self.control = self.pipe()
            self.status, status_w = self.pipe()
            os.set_blocking(self.control, False)
            os.set_blocking(self.status, False)
            self.spawn_attempted = True
            try:
                self.process = subprocess.Popen(
                    [sys.executable, "-I", "-B", str(ENTRY), str(self.slot.fileno())],
                    stdin=control_r,
                    stdout=status_w,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    pass_fds=(self.slot.fileno(),),
                    start_new_session=True,
                    env=dict(ENVIRONMENT),
                    cwd=str(ENTRY.parent),
                )
            except BaseException:
                self.fail("cleanup_unknown", uncertain=True)
            if self.process is not None:
                self.close(control_r)
                self.close(status_w)
                self.loop(clock, deadline)
        except BaseException:
            self.fail("cleanup_unknown", uncertain=True)
        finally:
            self.close_control()
            for fd in tuple(self.fds):
                self.close(fd)
            # A known Popen stays owned even when status or another descriptor fails.
            while self.process is not None and not (self.waited or self.wait_lost):
                self.wait()
                if not (self.waited or self.wait_lost):
                    time.sleep(0.05)
            self.release_slot()
        clean = not self.unknown and (not self.spawn_attempted or self.waited)
        return self.command_code, self.output, self.error, clean
