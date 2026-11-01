"""Deferred, sanitized errors without importing the storage boundary at startup."""

from contextlib import contextmanager
from functools import wraps
from inspect import signature


def error(code, status=409):
    from ara.documents.storage import DocumentError

    messages = {
        "validation_error": "Invalid request",
        "editor_error": "Editor operation failed",
        "editor_registry_expired": "Editor registry has expired",
        "editor_session_expired": "Editor session has expired",
        "stale_open": "Editor opening sequence has changed",
        "idempotency_conflict": "Editor opening attempt does not match",
        "checkpoint_conflict": "Document checkpoint has changed",
        "revision_exhausted": "Editor opening sequence is exhausted",
        "editor_limit_exceeded": "Editor retained resource limit exceeded",
        "editor_document_unsupported": "Document has no supported editor position",
        "stale_command": "Editor command sequence has changed",
        "editor_operation_pending": "Resolve the pending editor operation first",
        "docx_conflict": "Document storage revision has changed",
        "editor_operation_missing": "No matching editor operation is available",
        "editor_save_requires_commit": "Dirty document save requires the commit pipeline",
    }
    raise DocumentError(status, code, messages[code])


def validate(condition):
    if not condition:
        error("validation_error", 422)


@contextmanager
def native_errors():
    from ara.docx_package import DocxError
    from ara.docx_package.boundaries import BoundaryError
    from ara.docx_package.checkpoint import CheckpointError
    from ara.docx_package.editor import EditorError
    from ara.docx_package.formatting import FormattingError
    from ara.docx_package.projection import ProjectionError
    from ara.docx_package.ranges import RangeError
    from ara.docx_package.session import SessionError
    from ara.docx_package.structure import StructureError

    try:
        yield
    except (
        DocxError,
        BoundaryError,
        CheckpointError,
        EditorError,
        FormattingError,
        ProjectionError,
        RangeError,
        SessionError,
        StructureError,
    ) as exc:
        from ara.documents.storage import DocumentError

        if exc.code == "stale_revision":
            error("stale_command")
        raise DocumentError(
            413 if exc.code.endswith("_limit_exceeded") else 422, exc.code, exc.message
        ) from None


@contextmanager
def editor_boundary():
    from ara.documents.storage import DocumentError
    from ara.docx_package.editor import EditorError

    try:
        yield
    except DocumentError:
        raise
    except EditorError as exc:
        if exc.code == "invalid_selection":
            error("editor_document_unsupported", 422)
        error("editor_error", 500)
    except Exception:
        error("editor_error", 500)


def safe(method):
    parameters = signature(method)

    @wraps(method)
    def call(*args, **kwargs):
        try:
            parameters.bind(*args, **kwargs)
        except TypeError:
            error("validation_error", 422)
        with editor_boundary():
            return method(*args, **kwargs)

    return call
