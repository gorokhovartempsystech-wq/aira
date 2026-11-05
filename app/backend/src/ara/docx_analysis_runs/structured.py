"""Explicit structured saved checks; retries retain the original supported profile."""

from ara.docx_analysis.storage_codec import restore_source
from ara.docx_analysis.visible_lists import build_list_snapshot

from ._start import _retry_run, _start_saved


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
        builder=build_list_snapshot,
    )


def _stored_snapshot(source, limits):
    return restore_source(source, limits=limits).snapshot


def retry_run(runtime, *, client_request_id, command, execution, limits=None, queue_limit=16):
    return _retry_run(
        runtime,
        client_request_id=client_request_id,
        command=command,
        execution=execution,
        limits=limits,
        queue_limit=queue_limit,
        snapshot_loader=_stored_snapshot,
    )
