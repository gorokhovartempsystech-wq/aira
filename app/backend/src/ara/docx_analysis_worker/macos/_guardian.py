"""Private guardian: physical exit proof is independent of signal delivery."""

import os
import select
import signal
import stat
import subprocess
import sys
from uuid import UUID

from ..wire import StreamDecoder, WireBinding, encode_message
from ._bootstrap import TOKENS, TokenReader
from ._clock import DarwinClock
from ._errors import MacRuntimeError
from ._launch import CHILD_ENTRY, MINIMAL_ENV, MODES
from ._ownership import OwnedChild


def _closed_kind(*, exited, lost, exit_code, stop_requested, hard_fault, signal_error):
    if any(
        type(v) is not bool for v in (exited, lost, stop_requested, hard_fault, signal_error)
    ) or (
        exit_code is not None and (type(exit_code) is not int or not -(2**31) <= exit_code < 2**31)
    ):
        raise MacRuntimeError("runtime_unavailable")
    if not exited or lost or exit_code is None:
        return None
    if hard_fault:
        return "crashed"
    if stop_requested:
        return "stopped"
    return "crashed" if signal_error or exit_code != 0 else "clean"


def _send(fd, raw, clock, end):
    while raw:
        try:
            count = os.write(fd, raw)
            if count <= 0:
                return False
            raw = raw[count:]
        except BlockingIOError:
            if clock.now_ns() >= end:
                return False
            select.select([], [fd], [], 0.1)
        except OSError:
            return False
    return True


def _number(raw):
    value = int(raw)
    if str(value) != raw or not 0 <= value <= 2**63 - 1:
        raise ValueError()
    return value


def main(args):
    descriptors, child, gate_w = set(), None, None

    def drop(fd):
        if fd in descriptors:
            descriptors.remove(fd)
            os.close(fd)

    def pipe():
        pair = os.pipe()
        descriptors.update(pair)
        return pair

    try:
        run_id, attempt, deadline, lease, mode, *raw_fds = args
        binding = WireBinding(UUID(run_id), UUID(attempt))
        if str(binding.run_id) != run_id or str(binding.attempt_id) != attempt:
            return 75
        deadline, lease = _number(deadline), _number(lease)
        control, request, events, status, armed, slot = map(_number, raw_fds)
        incoming = {control, request, events, status, armed, slot}
        if (
            len(incoming) != 6
            or min(incoming) < 3
            or max(incoming) >= 2**31
            or mode not in MODES
            or not 0 < lease <= deadline
        ):
            return 75
        descriptors.update(incoming)
        for fd in incoming - {slot}:
            if not stat.S_ISFIFO(os.fstat(fd).st_mode):
                return 75
        info = os.fstat(slot)
        if not (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_size == 0
            and info.st_nlink == 1
        ):
            return 75
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        clock = DarwinClock()
        current = clock.now_ns()
        if not current < lease <= deadline or deadline - current > 300_000_000_000:
            return 75
        if lease - current > 15_000_000_000:
            return 75
        decoder = StreamDecoder(binding, lane="control")
        for fd in (control, status, armed):
            os.set_blocking(fd, False)
        stop_requested = hard_fault = False
        initial = False

        def controls(now):
            nonlocal lease, initial, stop_requested, hard_fault
            if now >= min(deadline, lease):
                stop_requested = True
                return
            try:
                data = os.read(control, 65536)
            except BlockingIOError:
                return
            if not data:
                decoder.finish()
                stop_requested = True
                return
            for message in decoder.feed(data):
                if message.kind == "stop":
                    if message.values["reason"] == "protocol":
                        hard_fault = True
                    else:
                        stop_requested = True
                else:
                    new_d, new_l = message.values["deadline_ns"], message.values["lease_ns"]
                    if (
                        new_d != deadline
                        or new_l > now + 15_000_000_000
                        or (not initial and new_l != lease)
                    ):
                        raise ValueError()
                    lease, initial = new_l, True
                    if now >= lease:
                        stop_requested = True

        while not initial and not (stop_requested or hard_fault):
            select.select([control], [], [], 0.1)
            controls(clock.now_ns())
        if stop_requested or hard_fault:
            return 75
        gate_r, gate_w = pipe()
        prepared_r, prepared_w = pipe()
        err_r, err_w = pipe()
        for fd in (gate_w, prepared_r, err_r):
            os.set_blocking(fd, False)
        controls(clock.now_ns())
        if stop_requested or hard_fault:
            return 75
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                str(CHILD_ENTRY),
                run_id,
                attempt,
                str(deadline),
                str(lease),
                mode,
                str(slot),
                str(gate_r),
                str(prepared_w),
            ],
            shell=False,
            close_fds=True,
            pass_fds=(slot, gate_r, prepared_w),
            start_new_session=True,
            cwd=str(CHILD_ENTRY.parent),
            env=dict(MINIMAL_ENV),
            stdin=request,
            stdout=events,
            stderr=err_w,
        )
        child = OwnedChild(process)
        for fd in (request, events, gate_r, prepared_w, err_w):
            drop(fd)
        prepared = TokenReader("prepared")
        did_go = prepared_eof = stderr_eof = False
        stderr_count = 0
        exit_at = None
        clock_failed = False
        while True:
            try:
                current = clock.now_ns()
            except Exception:
                clock_failed = hard_fault = True
            if not (stop_requested or hard_fault or child.signal_error):
                try:
                    controls(current)
                except Exception:
                    hard_fault = True
            if not did_go and (stop_requested or hard_fault):
                drop(prepared_r)
                prepared_eof = True
            if not prepared_eof:
                try:
                    data = os.read(prepared_r, 9)
                    if data:
                        prepared.feed(data)
                    else:
                        prepared.finish()
                        prepared_eof = True
                except BlockingIOError:
                    pass
                except Exception:
                    hard_fault = True
                    prepared_eof = True
            if not stderr_eof:
                try:
                    data = os.read(err_r, 65536)
                    stderr_count += len(data)
                    stderr_eof = not data
                    if stderr_count > 65536:
                        hard_fault = True
                except BlockingIOError:
                    pass
                except OSError:
                    hard_fault = True
            hard_fault = hard_fault or child.hard_fault
            teardown = stop_requested or hard_fault or child.signal_error
            if teardown:
                drop(gate_w)
            child._poll(current, stop=teardown, force=hard_fault)
            hard_fault = hard_fault or child.hard_fault
            if child.lost:
                return 75
            if child.exited:
                if not did_go and not stop_requested:
                    hard_fault = True
                if exit_at is None:
                    exit_at = current
                if stderr_eof:
                    break
                if clock_failed or current >= exit_at + 2_000_000_000:
                    hard_fault = True
                    break
            elif not did_go and prepared.ready and not teardown:
                try:
                    controls(clock.now_ns())
                    child._poll(clock.now_ns())
                    if child.exited and not stop_requested:
                        hard_fault = True
                    if not (stop_requested or hard_fault or child.exited or child.fault):
                        if os.write(gate_w, TOKENS["gate"]) != 8:
                            raise OSError()
                        if os.write(armed, TOKENS["armed"]) != 8:
                            raise OSError()
                        drop(armed)
                        did_go = True
                except Exception:
                    hard_fault = True
            readers = [] if (stop_requested or hard_fault or child.signal_error) else [control]
            if not prepared_eof:
                readers.append(prepared_r)
            if not stderr_eof:
                readers.append(err_r)
            select.select(readers, [], [], 0.1)
        kind = _closed_kind(
            exited=child.exited,
            lost=child.lost,
            exit_code=child.exit_code,
            stop_requested=stop_requested,
            hard_fault=hard_fault or child.hard_fault,
            signal_error=child.signal_error,
        )
        if kind is None:
            return 75
        drop(slot)
        raw = encode_message(
            binding,
            kind="closed",
            seq=0,
            values=dict(exit_kind=kind, exit_code=child.exit_code, cleanup_confirmed=True),
        )
        if clock_failed:
            return 0 if os.write(status, raw) == len(raw) else 75
        return 0 if _send(status, raw, clock, clock.now_ns() + 2_000_000_000) else 75
    except BaseException:
        try:
            drop(gate_w)
        except Exception:
            pass
        if child is not None and not child.exited and not child.lost:
            try:
                while not child.exited and not child.lost:
                    child._poll(0, force=True)
                    select.select([], [], [], 0.1)
            except BaseException:
                pass
        return 75
    finally:
        if child is not None:
            try:
                child.close()
            except Exception:
                pass
        for fd in tuple(descriptors):
            try:
                drop(fd)
            except OSError:
                pass
