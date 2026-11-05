"""Shell-neutral execution/recovery; the host must own the application data home."""

from threading import Lock

from . import storage
from .state import classify

# Local serialization supplements the existing single-owner desktop data-home.
# Native calls run outside database transactions; errors retain durable intent.
_gate = Lock()


def resume(runtime, document_id, *, files):
    """files.observe(path) -> Observation|None; files.write(path, bytes, expected).

    None means proven missing file, never permission failure. write must enforce
    expected identity/content or absence, publish atomically and await completion.
    Exceptions leave the intent in SQL for an explicit retry/reconciliation.
    This service neither chooses a path nor exposes filesystem access over HTTP.
    """
    with _gate:
        before = storage.read(runtime, document_id)
        intent = before.state.pending
        if intent is None:
            return before
        observed = _observe(files, intent.path)
        outcome = classify(intent, observed)
        if outcome == "conflict":
            storage.reject("file_observation_conflict")
        if outcome == "unchanged":
            try:
                files.write(intent.path, before.payload, intent.previous)
            except Exception:
                storage.reject("file_write_uncertain")
            observed = _observe(files, intent.path)
            if observed is None:
                storage.reject("file_write_unconfirmed")
        from uuid import UUID

        return storage.finish(
            runtime, document_id, operation_id=UUID(intent.operation_id), observed=observed
        )


def _observe(files, path):
    try:
        return files.observe(path)
    except Exception:
        storage.reject("file_read_failed")
