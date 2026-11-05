"""Small private tokens, separate from frozen aira-worker/1 frames."""

from ._errors import MacRuntimeError

TOKENS = {"prepared": b"AIRA-N1P", "gate": b"AIRA-N1G", "armed": b"AIRA-N1A"}


class TokenReader:
    def __init__(self, kind, eof_required=True):
        if type(kind) is not str or kind not in TOKENS or type(eof_required) is not bool:
            raise MacRuntimeError("validation_error")
        self._token = TOKENS[kind]
        self._eof_required = eof_required
        self._data = b""
        self._finished = self._failed = False

    @property
    def ready(self):
        return (
            not self._failed
            and self._data == self._token
            and (self._finished or not self._eof_required)
        )

    def feed(self, chunk):
        if self._failed or self._finished or type(chunk) is not bytes:
            self._fail()
        if len(self._data) + len(chunk) > 8:
            self._fail()
        self._data += chunk
        if not self._token.startswith(self._data):
            self._fail()

    def finish(self):
        if self._failed or not self._eof_required or self._data != self._token:
            self._fail()
        self._finished = True

    def _fail(self):
        self._failed, self._data = True, b""
        raise MacRuntimeError("runtime_unavailable")
