"""Canonical namespaces for validated, immutable checkpoint and save identities."""

import json
from hashlib import sha256


def _fingerprint(prefix, value):
    return sha256(
        prefix
        + json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def checkpoint_fingerprint(
    action,
    document_id,
    expected,
    request_id,
    *,
    base_revision=None,
    base_sha256=None,
    data=None,
    metadata=None,
    operation_id=None,
):
    value = {
        "version": 1,
        "action": action,
        "document_id": str(document_id),
        "expected_checkpoint_revision": str(expected),
        "request_id": str(request_id),
    }
    if action in ("put", "prepare"):
        value.update(
            base_storage_revision=str(base_revision),
            base_sha256=base_sha256,
            working_sha256=sha256(data).hexdigest(),
            working_size_bytes=len(data),
            metadata=metadata,
        )
    if action == "prepare":
        value["operation_id"] = str(operation_id)
    return _fingerprint(b"ara.docx.editor-checkpoint.v1\0", value)


def pending_fingerprint(document_id, revision, base_revision, base_sha256, data, metadata):
    return save_identity_fingerprint(
        document_id,
        revision,
        base_revision,
        base_sha256,
        sha256(data).hexdigest(),
        len(data),
        metadata,
    )


def save_identity_fingerprint(
    document_id,
    revision,
    base_revision,
    base_sha256,
    working_sha256,
    working_size_bytes,
    metadata,
):
    value = {
        "version": 1,
        "document_id": str(document_id),
        "operation_id": metadata["pending"]["operation_id"],
        "prepared_checkpoint_revision": str(revision),
        "base_storage_revision": str(base_revision),
        "base_sha256": base_sha256,
        "working_sha256": working_sha256,
        "working_size_bytes": working_size_bytes,
        "origin": metadata["origin"],
        "selection": metadata["selection"],
    }
    return _fingerprint(b"ara.docx.editor-save.v1\0", value)
