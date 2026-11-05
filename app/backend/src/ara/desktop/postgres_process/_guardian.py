"""Isolated direct-child waiter. Stop is SIGTERM to the owned child, never its group."""

import base64
import os
import select
import signal
import stat
import subprocess
import sys

from ara.docx_analysis_worker.macos import DarwinClock

from ._models import CommandError, require
from ._wire import BOOTSTRAP_LIMIT, ENVIRONMENT, OUTPUT_LIMIT, frame, read_bootstrap


def send(raw, clock):
    try:
        end = clock.now_ns() + 2_000_000_000
        while raw:
            try:
                count = os.write(1, raw)
                if count <= 0:
                    return False
                raw = raw[count:]
            except BlockingIOError:
                if clock.now_ns() >= end:
                    return False
                select.select([], [1], [], 0.05)
        return True
    except BaseException:
        return False


def request(clock, stop):
    deadline = clock.now_ns() + 15_000_000_000
    collected = bytearray()
    while not stop[0] and clock.now_ns() < deadline:
        try:
            raw = os.read(0, 8192)
        except BlockingIOError:
            select.select([0], [], [], 0.05)
            continue
        if not raw:
            return None
        collected.extend(raw)
        require(len(collected) <= BOOTSTRAP_LIMIT, "protocol_error")
        if b"\n" in collected:
            body, _, tail = collected.partition(b"\n")
            require(not tail, "protocol_error")
            value = read_bootstrap(bytes(body))
            # Do not launch if the complete request was followed by parent death/Stop.
            try:
                extra = os.read(0, 1)
            except BlockingIOError:
                return value
            if not extra:
                return None
            raise CommandError("protocol_error")
    return None


class Child:
    def __init__(self, request_value, slot, clock, stop):
        self.request, self.slot, self.clock, self.stop = request_value, slot, clock, stop
        self.process = None
        self.readers = {}
        self.fds = set()
        self.output = bytearray()
        self.error = self.code = None
        self.uncertain = self.waited = self.wait_lost = self.signalled = False

    def fail(self, code, *, uncertain=False):
        self.error = self.error or code
        self.uncertain |= uncertain
        self.stop[0] = True

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

    def control(self):
        try:
            raw = os.read(0, 8192)
        except BlockingIOError:
            return
        except OSError:
            self.fail("protocol_error")
            return
        if raw:
            self.fail("protocol_error")
        else:
            self.stop[0] = True

    def signal_and_wait(self):
        if self.process is None or self.waited or self.wait_lost:
            return
        if self.stop[0] and not self.signalled:
            self.signalled = True
            try:
                os.kill(self.process.pid, signal.SIGTERM)
            except BaseException:
                self.fail("process_unavailable")
        try:
            pid, status = os.waitpid(self.process.pid, os.WNOHANG)
            if pid == 0:
                return
            if pid != self.process.pid or not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
                raise ChildProcessError()
            self.code = os.waitstatus_to_exitcode(status)
            self.process.returncode = self.code
            self.waited = True
        except BaseException:
            self.wait_lost = True
            self.fail("cleanup_unknown", uncertain=True)

    def drain(self):
        for fd, stdout in tuple(self.readers.items()):
            try:
                raw = os.read(fd, 65536)
            except BlockingIOError:
                continue
            except OSError:
                raw = b""
                self.fail("cleanup_unknown", uncertain=True)
            if not raw:
                del self.readers[fd]
                self.close(fd)
            elif stdout and self.request["capture"] and self.error != "output_limit":
                if len(self.output) + len(raw) > OUTPUT_LIMIT:
                    self.output.clear()
                    self.fail("output_limit")
                else:
                    self.output.extend(raw)

    def run(self):
        try:
            out_r, out_w = self.pipe()
            err_r, err_w = self.pipe()
            self.readers = {out_r: True, err_r: False}
            for fd in self.readers:
                os.set_blocking(fd, False)
            try:
                self.process = subprocess.Popen(
                    self.request["argv"],
                    cwd=self.request["cwd"],
                    stdin=subprocess.DEVNULL,
                    stdout=out_w,
                    stderr=err_w,
                    close_fds=True,
                    pass_fds=(self.slot,),
                    start_new_session=True,
                    env=dict(ENVIRONMENT),
                )
            except BaseException:
                self.fail("cleanup_unknown", uncertain=True)
            if self.process is not None:
                self.close(out_w)
                self.close(err_w)
                if not send(frame({"event": "started"}), self.clock):
                    self.stop[0] = True
                while True:
                    self.control()
                    self.drain()
                    self.signal_and_wait()
                    if self.wait_lost or (self.waited and (not self.readers or self.uncertain)):
                        break
                    # EOF control stays readable; omit it once Stop has been observed.
                    inputs = list(self.readers) + ([] if self.stop[0] else [0])
                    select.select(inputs, [], [], 0.05)
        except BaseException:
            self.fail("cleanup_unknown", uncertain=True)
        finally:
            # Unexpected local failure still requests smart termination of the known child.
            while self.process is not None and not (self.waited or self.wait_lost):
                self.stop[0] = True
                self.signal_and_wait()
                self.drain()
                if not (self.waited or self.wait_lost):
                    select.select([], [], [], 0.05)
            for fd in tuple(self.fds):
                self.close(fd)
        send(
            frame(
                dict(
                    event="finished",
                    returncode=self.code,
                    error_code=self.error,
                    stdout=base64.b64encode(bytes(self.output)).decode("ascii"),
                    uncertain=self.uncertain,
                )
            ),
            self.clock,
        )
        return 75 if self.uncertain else 0


def main(arguments):
    require(sys.platform == "darwin", "platform_unavailable")
    require(len(arguments) == 1, "protocol_error")
    slot = int(arguments[0])
    require(str(slot) == arguments[0] and 3 <= slot < 2**31, "protocol_error")
    info = os.fstat(slot)
    require(
        stat.S_ISREG(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_uid == os.geteuid()
        and info.st_nlink == 1
        and info.st_size == 0,
        "protocol_error",
    )
    for fd in (0, 1):
        require(stat.S_ISFIFO(os.fstat(fd).st_mode), "protocol_error")
        os.set_blocking(fd, False)
    stop = [False]

    def stopping(number, current_frame):
        stop[0] = True

    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    clock = DarwinClock()
    value = request(clock, stop)
    if value is None:
        return 0
    return Child(value, slot, clock, stop).run()
