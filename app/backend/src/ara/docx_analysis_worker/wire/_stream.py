"""Single-frame bounded incremental state machine, poisoned on peer failures."""

from ._codec import CAPS, COUNTS, SCHEMAS, TOTALS, WireError, binding_copy, decode, digest, require


class StreamDecoder:
    def __init__(self, binding, *, lane, expected_execution_spec_sha256=None):
        self._binding = binding_copy(binding)
        if type(lane) is not str or lane not in CAPS:
            raise WireError("validation_error")
        if (lane == "events" and not digest(expected_execution_spec_sha256)) or (
            lane != "events" and expected_execution_spec_sha256 is not None
        ):
            raise WireError("validation_error")
        self._lane, self._spec = lane, expected_execution_spec_sha256
        self._buffer = bytearray()
        self._length = None
        self._count = self._total = self._seq = 0
        self._phase, self._deadline = "start", None
        self._failed = self._finished = False

    def __repr__(self):
        return "<StreamDecoder>"

    def feed(self, chunk):
        if type(chunk) is not bytes or len(chunk) > 65536:
            raise WireError("validation_error")
        if self._failed or self._finished:
            raise WireError()
        messages = []
        pos = 0
        try:
            while pos < len(chunk):
                require(self._phase != "terminal")
                target = 4 if self._length is None else self._length
                size = min(target - len(self._buffer), len(chunk) - pos)
                self._buffer.extend(chunk[pos : pos + size])
                pos += size
                if len(self._buffer) != target:
                    continue
                if self._length is None:
                    length = int.from_bytes(self._buffer, "big")
                    self._buffer.clear()
                    require(0 < length <= CAPS[self._lane])
                    require(
                        self._count < COUNTS[self._lane]
                        and self._total + length <= TOTALS[self._lane]
                    )
                    self._count += 1
                    self._total += length
                    self._length = length
                else:
                    message = decode(self._binding, bytes(self._buffer))
                    self._buffer.clear()
                    self._length = None
                    self._accept(message)
                    messages.append(message)
            return tuple(messages)
        except Exception:
            self._failed = True
            self._buffer.clear()
            raise WireError() from None

    def _accept(self, message):
        require(SCHEMAS[message.kind][0] == self._lane and message.seq == self._seq)
        self._seq += 1
        kind = message.kind
        if self._lane in ("request", "status") or kind in ("result", "error", "stop"):
            if kind == "result":
                require(self._phase == "analyzing")
            self._phase = "terminal"
        elif kind == "ready":
            require(
                self._phase == "start" and message.values["execution_spec_sha256"] == self._spec
            )
            self._phase = "ready"
        elif kind == "stage":
            stage = message.values["stage"]
            require(
                (self._phase, stage) in (("ready", "loading_model"), ("loading_model", "analyzing"))
            )
            self._phase = stage
        elif kind == "permit":
            deadline = message.values["deadline_ns"]
            require(self._deadline is None or self._deadline == deadline)
            self._deadline = deadline

    def finish(self):
        if self._failed:
            raise WireError()
        if self._finished:
            return
        if (
            self._buffer
            or self._length is not None
            or (self._lane != "control" and self._phase != "terminal")
        ):
            self._failed = True
            self._buffer.clear()
            raise WireError()
        self._finished = True
