"""Trusted bounded publication port; the desktop dispatcher supplies its own adapter."""

from abc import ABC, abstractmethod

from ara.docx_analysis_worker.control import AttemptControl

from . import _storage


def publication_fail(code):
    from ara.documents.storage import DocumentError

    message = {
        "publication_in_progress": "Publication operation is already active",
        "publication_conflict": "Publication reply does not match",
    }[code]
    raise DocumentError(409, code, message, False)


class PublicationPort(ABC):
    @abstractmethod
    def view(self): ...

    @abstractmethod
    def reserve(self): ...

    @abstractmethod
    def settle(self, permit, *, outcome): ...


class DirectPublicationPort(PublicationPort):
    def __init__(self, control, *, clock):
        if type(control) is not AttemptControl or not callable(clock):
            _storage.fail("validation_error", 422)
        self._control, self._clock = control, clock

    def __repr__(self):
        return "<DirectPublicationPort>"

    def view(self):
        return self._control.view()

    def reserve(self):
        return self._control.reserve(now_ns=self._clock())

    def settle(self, permit, *, outcome):
        return self._control.settle(permit, outcome=outcome, now_ns=self._clock())
