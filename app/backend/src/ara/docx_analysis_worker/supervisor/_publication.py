"""Wake-only wrapper; settlement is acknowledged before another outcome is sent."""

from ara.docx_analysis_runs.guarded_port import PublicationPort


class WakePublicationPort(PublicationPort):
    def __init__(self, delegate, wake):
        self._delegate, self._wake = delegate, wake
        self._pending = None
        self.resolved = None

    @property
    def pending(self):
        return self._pending is not None

    def view(self):
        return self._delegate.view()

    def reserve(self):
        self._wake.set()
        return self._delegate.reserve()

    def _send(self, token, outcome):
        self._wake.set()
        result = self._delegate.settle(token, outcome=outcome)
        if outcome != "unknown":
            self.resolved = token, outcome
        self._pending = None
        return result

    def flush_settlement(self):
        if self._pending is not None:
            return self._send(*self._pending)
        return self.view()

    def settle(self, permit, *, outcome):
        if self._pending is not None and self._pending != (permit, outcome):
            self.flush_settlement()
        self._pending = permit, outcome
        return self._send(permit, outcome)
