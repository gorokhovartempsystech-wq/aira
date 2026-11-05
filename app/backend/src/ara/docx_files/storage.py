"""Scoped transactions commit intents before a trusted host performs file IO."""

from hashlib import sha256
from pathlib import PurePosixPath, PureWindowsPath
from uuid import UUID

from ara.docx_documents.storage import _document
from ara.models import DocxFileState

from .state import Binding, Intent, Observation, Snapshot, State, classify


def reject(code):
    from ara.documents.storage import DocumentError

    raise DocumentError(409, code, "File operation cannot proceed") from None


def path_valid(path):
    return (
        isinstance(path, str)
        and 0 < len(path) <= 4096
        and "\0" not in path
        and (PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute())
        and path.lower().endswith(".docx")
    )


def snapshot(row):
    if row is None:
        return Snapshot(0, State())
    state = State.model_validate(row.state)
    if bool(state.pending) != (row.payload is not None):
        raise ValueError("invalid_file_state")
    if state.pending and sha256(row.payload).hexdigest() != state.pending.sha256:
        raise ValueError("invalid_file_payload")
    return Snapshot(row.version, state, row.payload)


def store(session, document_id, before, state, payload=None):
    if before.version >= 9223372036854775807:
        reject("file_version_exhausted")
    row = session.get(DocxFileState, document_id)
    if row is None:
        row = DocxFileState(document_id=document_id)
        session.add(row)
    row.version = before.version + 1
    row.state = state.model_dump()
    row.payload = payload
    session.flush()
    return snapshot(row)


def read(runtime, document_id: UUID):
    from ara.documents.storage import _session

    with _session(runtime) as session:
        _document(session, runtime, document_id)
        result = snapshot(session.get(DocxFileState, document_id))
    return result


def attach(runtime, document_id: UUID, observed: Observation):
    """Initial explicit import binding only; never refresh external modifications."""
    if not isinstance(observed, Observation) or not path_valid(observed.path):
        reject("invalid_file_observation")
    from ara.documents.storage import _session

    with _session(runtime) as session:
        doc = _document(session, runtime, document_id, writing=True)
        before = snapshot(session.get(DocxFileState, document_id))
        if before.version:
            if (
                before.state.pending is None
                and before.state.binding is not None
                and before.state.binding.observed == observed
            ):
                return before
            reject("file_already_bound")
        if observed.sha256 != doc.current_sha256:
            reject("file_content_conflict")
        result = store(
            session,
            document_id,
            before,
            State(binding=Binding(observed=observed, saved_revision=doc.storage_revision)),
        )
    return result


def prepare(
    runtime,
    document_id: UUID,
    *,
    operation_id: UUID,
    expected_version: int,
    storage_revision: int,
    source_sha256: str,
    save_as: str | None = None,
):
    """Capture exact committed DOCX bytes, keeping them through later internal saves."""
    if (
        not isinstance(operation_id, UUID)
        or type(expected_version) is not int
        or expected_version < 0
    ):
        reject("invalid_file_intent")
    if save_as is not None and not path_valid(save_as):
        reject("invalid_file_path")
    from ara.documents.storage import _session

    with _session(runtime) as session:
        doc = _document(session, runtime, document_id, writing=True)
        before = snapshot(session.get(DocxFileState, document_id))
        state = before.state.model_copy(deep=True)
        existing = state.pending or state.completed
        if existing and existing.operation_id == operation_id.hex:
            requested_path = (
                save_as
                if save_as is not None
                else (state.binding.observed.path if state.binding else None)
            )
            if (
                existing.expected_version,
                existing.saved_revision,
                existing.sha256,
                existing.path,
            ) != (expected_version, storage_revision, source_sha256, requested_path):
                reject("file_intent_conflict")
            return before
        if state.pending or before.version != expected_version:
            reject("file_version_conflict")
        if (doc.storage_revision, doc.current_sha256) != (storage_revision, source_sha256):
            reject("file_content_conflict")
        if (
            not 0 < len(doc.current_data) <= 33554432
            or sha256(doc.current_data).hexdigest() != source_sha256
        ):
            raise ValueError("invalid_docx_payload")
        if save_as is None and state.binding is None:
            reject("file_destination_required")
        previous = state.binding.observed if save_as is None else None
        state.pending = Intent(
            operation_id=operation_id.hex,
            expected_version=expected_version,
            path=save_as if save_as is not None else previous.path,
            previous=previous,
            sha256=source_sha256,
            saved_revision=storage_revision,
        )
        state.completed = None
        result = store(session, document_id, before, state, doc.current_data)
    return result


def finish(runtime, document_id: UUID, *, operation_id: UUID, observed: Observation):
    """Trusted host readback, also usable to reconcile a crash after file publication."""
    from ara.documents.storage import _session

    with _session(runtime) as session:
        _document(session, runtime, document_id, writing=True)
        before = snapshot(session.get(DocxFileState, document_id))
        state = before.state.model_copy(deep=True)
        if state.pending is None:
            if (
                state.completed
                and state.completed.operation_id == operation_id.hex
                and state.binding.observed == observed
            ):
                return before
            reject("file_intent_missing")
        if (
            state.pending.operation_id != operation_id.hex
            or classify(state.pending, observed) != "written"
        ):
            reject("file_observation_conflict")
        state.binding = Binding(observed=observed, saved_revision=state.pending.saved_revision)
        state.completed, state.pending = state.pending, None
        result = store(session, document_id, before, state)
    return result


def abort(runtime, document_id: UUID, *, operation_id: UUID, observed: Observation | None):
    """Host must first quiesce writer; None means confirmed absence, not read error."""
    from ara.documents.storage import _session

    with _session(runtime) as session:
        _document(session, runtime, document_id, writing=True)
        before = snapshot(session.get(DocxFileState, document_id))
        state = before.state.model_copy(deep=True)
        if not state.pending or state.pending.operation_id != operation_id.hex:
            reject("file_intent_missing")
        # Written takes precedence when old/new content are identical: reconcile it.
        if classify(state.pending, observed) != "unchanged":
            reject("file_observation_conflict")
        state.pending = None
        result = store(session, document_id, before, state)
    return result


def retarget(runtime, document_id: UUID, *, expected_version: int, operation_id: UUID, path: str):
    """Explicit Save As of retained bytes. Host must first quiesce the old writer."""
    if not path_valid(path) or not isinstance(operation_id, UUID):
        reject("invalid_file_intent")
    from ara.documents.storage import _session

    with _session(runtime) as session:
        _document(session, runtime, document_id, writing=True)
        before = snapshot(session.get(DocxFileState, document_id))
        state = before.state.model_copy(deep=True)
        if (
            type(expected_version) is not int
            or before.version != expected_version
            or not state.pending
        ):
            reject("file_version_conflict")
        if state.pending.operation_id == operation_id.hex:
            reject("file_intent_conflict")
        state.pending = Intent(
            operation_id=operation_id.hex,
            expected_version=before.version,
            path=path,
            previous=None,
            sha256=state.pending.sha256,
            saved_revision=state.pending.saved_revision,
        )
        result = store(session, document_id, before, state, before.payload)
    return result
