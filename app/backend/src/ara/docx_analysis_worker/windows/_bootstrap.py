"""Bounded bootstrap tokens, separate from the worker wire protocol."""

from ._errors import WindowsRuntimeError

TOKENS = {"prepared": b"AIRA-N1P", "gate": b"AIRA-N1G", "armed": b"AIRA-N1A"}


class TokenReader:
    def __init__(self, kind, eof_required=True):
        if type(kind) is not str or kind not in TOKENS or type(eof_required) is not bool:
            raise WindowsRuntimeError("validation_error")
        self._token, self._require = TOKENS[kind], eof_required
        self._data, self._done, self._bad = b"", False, False

    def feed(self, chunk):
        if self._bad or self._done or type(chunk) is not bytes:
            self._fail()
        if len(self._data) + len(chunk) > 8:
            self._fail()
        self._data += chunk
        if not self._token.startswith(self._data):
            self._fail()

    def finish(self):
        if self._bad or not self._require or self._data != self._token:
            self._fail()
        self._done = True

    @property
    def ready(self):
        return not self._bad and self._data == self._token and (self._done or not self._require)

    def _fail(self):
        self._bad, self._data = True, b""
        raise WindowsRuntimeError("runtime_unavailable")
