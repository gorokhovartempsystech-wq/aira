"""One data owner, bounded chunks/decoders, composite transport evidence only."""

from ..wire import StreamDecoder
from ._attempt_state import close_endpoints
from ._bootstrap import TokenReader


class Reader:
    def __init__(self, endpoint):
        self.endpoint, self.operation, self.eof = endpoint, None, False

    def poll(self):
        if self.eof:
            return None
        if self.operation is None:
            self.operation = self.endpoint.begin_read()
        result = self.operation.poll()
        if result is not None:
            self.operation = None
            if result.aborted:
                raise ValueError()
            self.eof = result.eof
        return result


def run(state):
    channels = state.await_handoff()
    if channels is None:
        with state.cv:
            state.quiescent["data"] = True
        return
    endpoints = [channels.request, channels.armed, channels.events, channels.status]
    try:
        pump(state, channels)
    except Exception:
        state.stop("transport", True)
    finally:
        close_endpoints(state, endpoints, "data")


def pump(s, channels):
    readers = {name: Reader(getattr(channels, name)) for name in ("armed", "events", "status")}
    armed = TokenReader("armed")
    events = StreamDecoder(s.binding, lane="events", expected_execution_spec_sha256=s.spec_sha)
    statuses = StreamDecoder(s.binding, lane="status")
    with s.cv:
        frame, s.frame = s.frame, None
    offset, write, complete, request_closed = 0, None, False, False
    status = reply = terminal = tail = None
    bad = set()
    while True:
        now = s.tick()
        with s.cv:
            stopped, permit, observation = s.stopped, s.permit_ready, s.observation
        if now is None:
            break
        if observation is not None and observation.process_exited and tail is None:
            tail = now + 2_000_000_000
        if tail is not None and (tail >= 2**63 or now >= tail):
            s.stop("protocol", True)
            break
        if stopped and not request_closed:
            request_closed = channels.request.close()
            frame = None
            if request_closed:
                write = None
        for name, reader in readers.items():
            try:
                result = reader.poll()
                if result is None:
                    continue
                # Fresh Stop/clock before decoding each bounded chunk.
                current = s.tick()
                with s.cv:
                    stopped = s.stopped
                if current is None:
                    continue
                if name in bad or stopped and name != "status":
                    continue
                if name == "armed":
                    if result.eof:
                        armed.finish()
                    else:
                        armed.feed(result.data)
                elif name == "events":
                    if result.eof:
                        events.finish()
                    else:
                        for message in events.feed(result.data):
                            if message.kind == "stage":
                                with s.cv:
                                    s.stage = message.values["stage"]
                            elif message.kind == "result":
                                terminal, reply = "result", message.payload
                            elif message.kind == "error":
                                terminal = "error"
                                s.stop("process", True)
                elif result.eof:
                    statuses.finish()
                    with s.cv:
                        s.status = status
                else:
                    for message in statuses.feed(result.data):
                        status = message
                        if tail is None:
                            tail = current + 2_000_000_000
            except Exception:
                bad.add(name)
                s.stop("protocol", True)
        now = s.tick()
        with s.cv:
            live = now is not None and not (s.stopped or s.closing)
            closing = s.closing
        # Explicit shutdown may discard missing transport evidence after physical exit.
        # Cancellation/owner close below still has to reach actual I/O quiescence.
        if closing and observation is not None and observation.process_exited and request_closed:
            break
        if live and permit and armed.ready and not request_closed:
            if write is None:
                write = channels.request.begin_write(frame[offset : offset + 65536])
            result = write.poll()
            if result is not None:
                write = None
                if result.aborted or result.eof or result.count <= 0:
                    raise ValueError()
                offset += result.count
                if offset == len(frame):
                    request_closed = channels.request.close()
                    if request_closed:
                        complete, frame = True, None
                        with s.cv:
                            s.request_complete = True
        if (
            observation is not None
            and observation.process_exited
            and all(reader.eof for reader in readers.values())
            and request_closed
        ):
            valid = bool(permit and armed.ready and complete and terminal == "result" and not bad)
            with s.cv:
                s.transport_valid = valid
                if valid and not (s.stopped or s.hard or s.closing):
                    s.reply = reply
                s.natural = s.candidate_locked()
                natural = s.natural
                if natural and s.command is not None and s.command.outcome == "pending":
                    # Physical/transport completion makes an unaccepted heartbeat unnecessary.
                    s.command.outcome = "finished"
                s.cv.notify_all()
            if not natural and not s.stopped:
                s.stop("process", True)
            break
        s.pause(0.01)
