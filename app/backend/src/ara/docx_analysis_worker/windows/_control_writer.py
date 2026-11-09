"""One control endpoint owner; one command, no queued heartbeat permissions."""

from ..wire import encode_message
from ._attempt_state import close_endpoints
from ._errors import ClosedPipeError


class Writer:
    def __init__(self, state, endpoint):
        self.state, self.endpoint = state, endpoint
        self.seq = self.total = 0

    def send(self, lease, cutoff, command=None):
        try:
            return self._send(lease, cutoff, command)
        except ClosedPipeError:
            return self._closed(command)

    def _closed(self, command):
        s = self.state
        if command is None:
            s.stop("transport", True)
            return False
        # Reject renewal and let the data reader verify completion within
        # the already accepted lease. No new permission was delivered.
        with s.cv:
            s.control_eof = True
            if command.outcome == "pending":
                command.outcome = "rejected"
            s.cv.notify_all()
        return False

    def _send(self, lease, cutoff, command=None):
        s = self.state
        frame = encode_message(
            s.binding,
            kind="permit",
            seq=self.seq,
            values={"deadline_ns": str(s.deadline), "lease_ns": str(lease)},
        )
        if self.seq >= 512 or self.total + len(frame) - 4 > 1024 * 1024:
            s.stop("transport", True)
            return False
        self.seq += 1
        self.total += len(frame) - 4
        now = s.tick()
        with s.cv:
            live = not (s.stopped or s.closing or s.natural) and now is not None and now < cutoff
        if not live:
            if not (s.stopped or s.natural):
                s.stop("transport", True)
            return False
        op = self.endpoint.begin_write(frame)
        while True:
            now = s.tick()
            with s.cv:
                stopped = s.stopped or s.closing or s.natural
            if stopped:
                return False
            if now is None or now >= cutoff:
                s.stop("transport", True)
                return False
            result = op.poll()
            if result is not None:
                if result.eof and command is not None:
                    return self._closed(command)
                if result.aborted or result.eof or result.count != len(frame):
                    s.stop("transport", True)
                    return False
                now = s.tick()
                with s.cv:
                    accepted = (
                        now is not None
                        and now < cutoff
                        and not (s.stopped or s.closing or s.natural)
                        and (
                            command is None or s.command is command and command.outcome == "pending"
                        )
                    )
                    if accepted:
                        if command is None:
                            s.permit_ready = True
                        else:
                            command.receipt = True
                        s.cv.notify_all()
                if not accepted and not (s.stopped or s.natural):
                    s.stop("transport", True)
                return accepted
            s.pause(0.005)


def run(state):
    channels = state.await_handoff()
    if channels is None:
        with state.cv:
            state.quiescent["control"] = True
        return
    writer = Writer(state, channels.control)
    try:
        now = state.tick()
        if now is not None:
            writer.send(state.lease, min(state.deadline, state.lease, now + 50_000_000))
        while True:
            state.tick()
            with state.cv:
                if state.stopped or state.closing or state.natural or state.control_eof:
                    break
                command = state.command
                if command is not None and command.outcome != "pending":
                    state.command = None
                    state.cv.notify_all()
                    command = None
                send = command is not None and not command.receipt
            if send:
                writer.send(command.lease, command.cutoff, command)
            else:
                state.pause(0.005)
    except Exception:
        state.stop("transport", True)
    finally:
        close_endpoints(state, [channels.control], "control")
