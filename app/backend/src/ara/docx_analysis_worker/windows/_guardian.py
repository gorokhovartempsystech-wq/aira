"""Independent fixture guardian: bounded IO, continuous lease, retained process proof."""

from ..wire import StreamDecoder, encode_message
from ._adopt import launch_config
from ._bootstrap import TOKENS, TokenReader
from ._clock import WindowsClock
from ._errors import WindowsRuntimeError
from ._jobs import create_job
from ._pending import reap_pending
from ._pipes import create_pipe_pair
from ._spawn import SpawnRecord


class GuardianBudget:
    def __init__(self, binding, deadline, lease):
        self.decoder = StreamDecoder(binding, lane="control")
        self.deadline, self.lease, self._first = deadline, lease, lease
        self.initial = self.stopped = self.hard = False
        self.last = None

    def stop(self, hard=False):
        self.stopped, self.hard = True, self.hard or hard

    def check(self, now):
        if (
            type(now) is not int
            or not 0 <= now < 2**63
            or self.last is not None
            and now < self.last
        ):
            self.stop(True)
            return False
        self.last = now
        if now >= min(self.deadline, self.lease):
            self.stop()
        return not self.stopped

    def feed(self, data, now):
        if not self.check(now):
            return
        try:
            for message in self.decoder.feed(data):
                if message.kind == "stop":
                    self.stop(message.values["reason"] == "protocol")
                    break
                d, lease_value = int(message.values["deadline_ns"]), int(message.values["lease_ns"])
                if (
                    d != self.deadline
                    or not now < lease_value <= min(d, now + 15_000_000_000)
                    or not self.initial
                    and lease_value != self._first
                    or self.initial
                    and lease_value < self.lease
                ):
                    raise ValueError()
                self.initial, self.lease = True, lease_value
        except Exception:
            self.stop(True)

    def eof(self):
        if not self.stopped:
            try:
                self.decoder.finish()
            except Exception:
                self.stop(True)
        self.stop()


class Lane:
    """One IO owner, one operation, at most64KiB queued; no wait inside a turn."""

    def __init__(self, endpoint):
        self.endpoint, self.operation = endpoint, None
        self.buffer, self.eof, self.closing = b"", False, False

    def queue(self, data):
        if self.buffer or self.operation is not None or self.closing or not 0 < len(data) <= 65536:
            raise WindowsRuntimeError("runtime_busy")
        self.buffer = data

    @property
    def idle(self):
        return not self.buffer and self.operation is None

    def step(self):
        if self.closing:
            if self.endpoint.close():
                self.operation, self.buffer, self.eof = None, b"", True
            return None
        if self.eof:
            return None
        if self.operation is None:
            if self.endpoint._kind == "read":
                self.operation = self.endpoint.begin_read()
            elif self.buffer:
                self.operation = self.endpoint.begin_write(self.buffer)
            else:
                return None
        result = self.operation.poll()
        if result is None:
            return None
        self.operation = None
        if result.aborted:
            raise WindowsRuntimeError("runtime_unavailable")
        if result.eof:
            self.eof = True
        if self.endpoint._kind == "write":
            self.buffer = self.buffer[result.count :]
        return result

    def close(self):
        self.closing, self.buffer = True, b""
        self.step()
        return self.eof

    def wait_handle(self):
        return self.operation.event_handle() if self.operation is not None else None


def wait_turn(api, lanes, extra=()):
    handles = list(extra)
    for lane in lanes:
        h = lane.wait_handle()
        if h is not None:
            handles.append(h)
    api.wait(list(dict.fromkeys(handles)), 100)


def close_owned(api, resources, clock, cutoff):
    """Owner-loop drain. False leaves memory strongly retained until process teardown."""
    while True:
        complete = reap_pending()
        for resource in resources:
            try:
                result = resource.close()
                complete = (result is not False) and complete
            except Exception:
                return False
        if complete:
            return True
        if clock.now_ns() >= cutoff:
            return False
        api.wait([], 10)


def run(api, inherited, binding, deadline, lease, mode):
    clock, state = WindowsClock(), GuardianBudget(binding, deadline, lease)
    control, status, armed = (Lane(inherited[n]) for n in ("control", "status", "armed"))
    lanes, resources, job, child = [control, status, armed], list(inherited.values()), None, None
    prepared = gate = diagnostics = None
    stopped_at = exited_at = None
    go = arm_sent = status_sent = False
    diagnostic_count = 0
    reader = TokenReader("prepared")
    try:
        now = clock.now_ns()
        if not 0 < lease <= deadline <= now + 300_000_000_000 or lease > now + 15_000_000_000:
            raise ValueError()

        def guard():
            now = clock.now_ns()
            state.check(now)
            if api.io.wait_event(inherited["hard"].value, 0):
                state.stop(True)
            if api.io.wait_event(inherited["ordinary"].value, 0):
                state.stop()
            result = control.step()
            if result is not None:
                if result.eof:
                    state.eof()
                else:
                    state.feed(result.data, now)
            return state.check(clock.now_ns())

        while not state.initial and guard():
            wait_turn(api, [control], [inherited["ordinary"].value, inherited["hard"].value])
        if state.stopped:
            return 74
        pairs = []
        for sync in (False, False, True):
            pair = create_pipe_pair(
                deadline_ns=min(state.deadline, state.lease), clock=clock, synchronous_writer=sync
            )
            pairs.append(pair)
            resources += [pair.reader, pair.writer]
        pp, gp, dp = pairs
        prepared, gate, diagnostics = Lane(pp.reader), Lane(gp.writer), Lane(dp.reader)
        lanes += [prepared, gate, diagnostics]
        job = create_job(1)
        child = SpawnRecord(api, job)
        roles = {
            "slot": inherited["slot"].value,
            "request": inherited["request"].handle(),
            "events": inherited["events"].handle(),
            "prepared": pp.writer.handle(),
            "gate": gp.reader.handle(),
            "diagnostics": dp.writer.handle(),
            "stdin": inherited["stdin"].value,
        }
        if not guard():
            return 74
        child.create(
            lambda h: launch_config("M", binding, deadline, state.lease, mode, h, api),
            roles,
            ("stdin", "diagnostics", "diagnostics"),
        )
        for resource in (
            inherited["request"],
            inherited["events"],
            pp.writer,
            gp.reader,
            dp.writer,
        ):
            if resource.close() is False:
                raise ValueError()
        try:
            child.resume(guard)
        except WindowsRuntimeError:
            if not state.stopped or child.fault:
                raise
        while True:
            live = guard()
            now = clock.now_ns()
            child.poll()
            if child.fault:
                state.stop(True)
            if state.stopped:
                if stopped_at is None:
                    stopped_at = now
                gate.close()
                if not arm_sent:
                    armed.close()
                if state.hard or now - stopped_at >= 2_000_000_000:
                    child.terminate()
            # Data turns stay bounded; never accumulate diagnostics.
            diag = diagnostics.step()
            if diag is not None:
                diagnostic_count += len(diag.data)
                if diagnostic_count > 65536:
                    state.stop(True)
            if not go and live and not child.exited:
                chunk = prepared.step()
                if chunk is not None:
                    try:
                        if chunk.eof:
                            reader.finish()
                        else:
                            reader.feed(chunk.data)
                    except WindowsRuntimeError:
                        state.stop(True)
                if reader.ready and guard():
                    gate.queue(TOKENS["gate"])
                    go = True
            if go and not state.stopped:
                gate.step()
                if gate.idle and not arm_sent and guard():
                    armed.queue(TOKENS["armed"])
                    arm_sent = True
                if arm_sent:
                    armed.step()
                    if armed.idle:
                        armed.close()
            if child.exited:
                if exited_at is None:
                    exited_at = now
                if not go and not state.stopped:
                    state.stop(True)
                if job.active_count() != 0:
                    state.stop(True)
                    child.terminate()
                elif diagnostics.eof:
                    break
                if now - exited_at >= 2_000_000_000:
                    raise ValueError()
            if (
                state.stopped
                and stopped_at is not None
                and now - stopped_at >= 5_000_000_000
                and not child.exited
            ):
                raise ValueError()
            extra = []
            if not child.exited:
                extra.append(child._process.value)
            if not state.stopped:
                extra.append(inherited["ordinary"].value)
            if not state.hard:
                extra.append(inherited["hard"].value)
            wait_turn(api, lanes, extra)

        # Known M exited, diagnostics exhausted. Retire all non-status IO before ACK.
        if not child.close():
            raise ValueError()
        others = [r for r in resources if r is not inherited["status"]]
        if not close_owned(api, others, clock, clock.now_ns() + 2_000_000_000):
            raise ValueError()
        kind = (
            "crashed"
            if state.hard or child.fault or job.fault
            else ("stopped" if state.stopped else "clean" if child.exit_code == 0 else "crashed")
        )
        status.queue(
            encode_message(
                binding,
                kind="closed",
                seq=0,
                values={"exit_kind": kind, "exit_code": child.exit_code, "cleanup_confirmed": True},
            )
        )
        cutoff = clock.now_ns() + 2_000_000_000
        while not status.idle:
            if clock.now_ns() >= cutoff:
                raise ValueError()
            status.step()
            if not status.idle:
                wait_turn(api, [status])
        status_sent = status.close()
        job.close()
        return 0 if status_sent else 75
    except BaseException:
        if child is not None:
            try:
                child.terminate()
            except Exception:
                pass
        return 75
    finally:
        # Entry exits immediately after return: last Job close is emergency containment,
        # not a successful closed status. Retained pending memory is never freed early.
        if job is not None:
            try:
                job.close()
            except Exception:
                pass
