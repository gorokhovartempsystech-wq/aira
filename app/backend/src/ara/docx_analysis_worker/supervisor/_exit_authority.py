"""Issued, immutable decisions of the live coordinator; never client-supplied flags."""

import os
from dataclasses import dataclass
from threading import current_thread
from weakref import WeakKeyDictionary

from ara.docx_analysis_worker.control._models import Uncopyable

from ._runtime_models import SupervisorError

_KEY = object()
_ISSUED = WeakKeyDictionary()


class ExitAuthority(Uncopyable):
    def __new__(cls, key=None):
        if key is not _KEY:
            raise TypeError("exit authority is issued by its coordinator")
        return super().__new__(cls)

    def __repr__(self):
        return "<ExitAuthority>"


@dataclass(frozen=True, slots=True, repr=False)
class Decision:
    issuer: object
    entry: object
    owner: object
    project_id: object
    user_id: object
    summary: object
    command_sha256: str
    reason: str
    claim: object
    binding: object


class ExitIssuer:
    def __init__(self, owner, project_id, user_id):
        self.pid, self.thread = os.getpid(), current_thread()
        self.owner, self.project_id, self.user_id = owner, project_id, user_id
        self._live = {}

    def issue(self, entry):
        if self.pid != os.getpid() or current_thread() is not self.thread:
            raise SupervisorError("invalid_handle")
        if not entry.sealed or not entry.reason or entry.state is None:
            raise SupervisorError("invalid_handle")
        if entry.dispatcher is not None:
            view = entry.dispatcher.view()
            if view.publication_pending or view.control.phase in (
                "committing",
                "unknown",
                "succeeded",
            ):
                raise SupervisorError("busy")
        if entry.authority is not None:
            return entry.authority
        value = ExitAuthority(_KEY)
        decision = Decision(
            self,
            entry,
            self.owner,
            self.project_id,
            self.user_id,
            entry.state.summary,
            entry.encoded.sha256,
            entry.reason,
            entry.claim,
            entry.binding,
        )
        _ISSUED[value] = self.pid, decision
        self._live[value] = decision
        entry.authority = value
        return value

    def revoke(self, authority):
        self._live.pop(authority, None)


def decision(authority):
    item = _ISSUED.get(authority) if type(authority) is ExitAuthority else None
    if item is None or item[0] != os.getpid():
        raise SupervisorError("invalid_handle")
    result = item[1]
    if result.issuer._live.get(authority) is not result or not result.entry.sealed:
        raise SupervisorError("invalid_handle")
    return result
