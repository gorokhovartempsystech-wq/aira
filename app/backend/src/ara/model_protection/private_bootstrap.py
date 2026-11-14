"""Secret preamble on the existing owned pipe, outside persisted worker frames."""

from ara.docx_analysis_worker.wire import StreamDecoder

from . import ModelProtectionError

MAGIC = b"AIRA-KEY\x00\x01"
SIZE = len(MAGIC) + 32


def wrap_request(key, frame):
    if type(key) is not bytes or len(key) != 32 or type(frame) is not bytes:
        raise ModelProtectionError()
    return MAGIC + key + frame


class ProtectedRequestDecoder:
    """A fixed-size preamble; no secret bytes reach JSON parsing or diagnostics."""

    def __init__(self, binding):
        self._prefix = bytearray()
        self._key = None
        self._failed = False
        self._finished = False
        self._decoder = StreamDecoder(binding, lane="request")

    def feed(self, raw):
        if self._failed or self._finished or type(raw) is not bytes:
            raise ModelProtectionError()
        try:
            if self._key is None:
                count = min(len(raw), SIZE - len(self._prefix))
                self._prefix.extend(raw[:count])
                raw = raw[count:]
                if not MAGIC.startswith(bytes(self._prefix[: len(MAGIC)])):
                    raise ModelProtectionError()
                if len(self._prefix) < SIZE:
                    return ()
                self._key = bytes(self._prefix[len(MAGIC) :])
                self._prefix[:] = b"\x00" * len(self._prefix)
                self._prefix.clear()
            return self._decoder.feed(raw)
        except Exception:
            self._failed = True
            self._key = None
            self._prefix.clear()
            raise ModelProtectionError() from None

    def finish(self):
        if self._failed or self._key is None:
            raise ModelProtectionError()
        try:
            result = self._decoder.finish()
            self._finished = True
            return result
        except Exception:
            self._key = None
            self._failed = True
            raise ModelProtectionError() from None

    def take_key(self):
        if self._failed or not self._finished or self._key is None:
            raise ModelProtectionError()
        value, self._key = self._key, None
        return value
