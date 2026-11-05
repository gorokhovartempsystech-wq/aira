"""Prepare an immutable source outside locks, then atomically admit one run."""

from ara.docx_analysis.review import ReviewError
from ara.docx_analysis.storage_codec import (
    RetryCheckCommand,
    SavedCheckCommand,
    StorageCodecError,
    capture_source,
    encode_command,
)
from ara.docx_analysis.storage_codec._models import checked, uuid
from ara.docx_analysis.storage_codec._records import LOWER_ERRORS
from ara.docx_analysis.visible_main import build_visible_snapshot
from ara.docx_analysis_runs import _storage
from ara.docx_editor._models import SavedTarget

from ._models import TERMINAL


def preparation_error(error):
    from ara.documents.storage import DocumentError

    if isinstance(error, DocumentError):
        raise error
    if not isinstance(error, (StorageCodecError, *LOWER_ERRORS)):
        _storage.fail("storage_error")
    code = getattr(error, "code", None)
    if isinstance(error, StorageCodecError) and code == "invalid_input":
        _storage.fail("validation_error", 422)
    if type(code) is str and "limit" in code:
        _storage.fail("analysis_limit_exceeded", 413)
    if isinstance(error, ReviewError) and code == "empty_document":
        _storage.fail("empty_document", 422)
    if type(code) is str and code in (
        "unsupported_document",
        "invalid_package",
        "unsupported_package",
        "invalid_snapshot",
        "source_mismatch",
    ):
        _storage.fail("unsupported_analysis_content", 422)
    _storage.fail("storage_error")


def inputs(runtime, key, command, cls, limits, queue_limit):
    _storage.context(runtime)
    if (
        not uuid(key)
        or type(command) is not cls
        or type(queue_limit) is not int
        or not 1 <= queue_limit <= 16
    ):
        _storage.fail("validation_error", 422)
    try:
        limits = checked(limits)
        encoded = encode_command(command, limits=limits)
    except StorageCodecError as error:
        preparation_error(error)
    return limits, encoded


def start_saved(
    runtime, *, client_request_id, command, target_provider, execution, limits=None, queue_limit=16
):
    return _start_saved(
        runtime,
        client_request_id=client_request_id,
        command=command,
        target_provider=target_provider,
        execution=execution,
        limits=limits,
        queue_limit=queue_limit,
        builder=build_visible_snapshot,
    )


def _start_saved(
    runtime, *, client_request_id, command, target_provider, execution, limits, queue_limit, builder
):
    limits, encoded = inputs(
        runtime, client_request_id, command, SavedCheckCommand, limits, queue_limit
    )
    previous, created = _storage.lookup(runtime, command, client_request_id, encoded)
    if previous is not None:
        return previous
    try:
        if not callable(target_provider):
            _storage.fail("validation_error", 422)
        target = target_provider()
        if type(target) is not SavedTarget:
            _storage.fail("storage_error")
        target.__post_init__()
        if (
            target.registry_id,
            target.document_id,
            target.session_id,
            target.command_id,
            target.command_sequence,
            target.session_revision,
            target.storage_revision,
            target.sha256,
        ) != (
            command.registry_id,
            command.document_id,
            command.session_id,
            command.save_command_id,
            command.command_sequence,
            command.session_revision,
            command.storage_revision,
            command.source_sha256,
        ):
            _storage.fail("saved_target_conflict", 409)
        snapshot = builder(
            target.data,
            document_id=command.document_id,
            storage_revision=command.storage_revision,
            source_sha256=command.source_sha256,
            limits=limits.review.view,
        )
        bundle = capture_source(
            target.data, snapshot, command=command, execution=execution, limits=limits
        )
    except Exception as error:
        previous, _ = _storage.lookup(runtime, command, client_request_id, encoded)
        if previous is not None:
            return previous
        preparation_error(error)
    return _storage.enqueue(
        runtime, command, client_request_id, encoded, bundle, created, queue_limit
    )


def retry_run(runtime, *, client_request_id, command, execution, limits=None, queue_limit=16):
    return _retry_run(
        runtime,
        client_request_id=client_request_id,
        command=command,
        execution=execution,
        limits=limits,
        queue_limit=queue_limit,
        snapshot_loader=_legacy_snapshot,
    )


def _legacy_snapshot(source, limits):
    return build_visible_snapshot(
        source.source_data,
        document_id=source.document_id,
        storage_revision=source.storage_revision,
        source_sha256=source.source_sha256,
        limits=limits.review.view,
    )


def _retry_run(
    runtime, *, client_request_id, command, execution, limits, queue_limit, snapshot_loader
):
    limits, encoded = inputs(
        runtime, client_request_id, command, RetryCheckCommand, limits, queue_limit
    )
    previous, created = _storage.lookup(runtime, command, client_request_id, encoded)
    if previous is not None:
        return previous
    try:
        parent = _storage.get_run(
            runtime, document_id=command.document_id, run_id=command.retry_of_run_id
        )
        if parent.status not in TERMINAL:
            _storage.fail("analysis_in_progress", 409)
        old = _storage.get_source(
            runtime, document_id=command.document_id, run_id=parent.run_id, limits=limits
        )
        snapshot = snapshot_loader(old, limits)
        bundle = capture_source(
            old.source_data, snapshot, command=command, execution=execution, limits=limits
        )
    except Exception as error:
        previous, _ = _storage.lookup(runtime, command, client_request_id, encoded)
        if previous is not None:
            return previous
        preparation_error(error)
    return _storage.enqueue(
        runtime, command, client_request_id, encoded, bundle, created, queue_limit
    )
