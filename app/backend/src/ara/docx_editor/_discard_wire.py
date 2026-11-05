"""Explicit content-free discard plans; complete save identity survives cleanup."""

from ara.docx_documents._dto import _hash
from ara.docx_documents.save_models import SaveHandle
from ara.docx_package.checkpoint import CheckpointMetadata, CheckpointOrigin, PendingSave

from . import wire
from ._errors import validate


def decode_prepare(body):
    v = wire._shape(body, ("expected_checkpoint_revision", "request_id"))
    return dict(
        expected_checkpoint_revision=wire._counter(v["expected_checkpoint_revision"]),
        request_id=wire._uuid(v["request_id"]),
    )


def _handle(value):
    v = wire._shape(
        value,
        (
            "document_id",
            "prepared_checkpoint_revision",
            "base_storage_revision",
            "base_sha256",
            "working_sha256",
            "working_size_bytes",
            "metadata",
        ),
    )
    m = wire._shape(v["metadata"], ("selection", "origin", "pending"))
    o = wire._shape(m["origin"], ("session_id", "session_revision", "position_id"))
    p = wire._shape(m["pending"], ("operation_id", "request_sha256"))
    validate(all(_hash(d) for d in (v["base_sha256"], v["working_sha256"], p["request_sha256"])))
    try:
        return SaveHandle(
            wire._uuid(v["document_id"]),
            wire._counter(v["prepared_checkpoint_revision"]),
            wire._counter(v["base_storage_revision"]),
            v["base_sha256"],
            v["working_sha256"],
            wire._int(v["working_size_bytes"], 33554432),
            CheckpointMetadata(
                wire._selection(m["selection"]),
                CheckpointOrigin(
                    wire._uuid(o["session_id"]),
                    wire._counter(o["session_revision"]),
                    wire._counter(o["position_id"]),
                ),
                PendingSave(wire._uuid(p["operation_id"]), p["request_sha256"]),
            ),
        )
    except (ValueError, TypeError, AttributeError):
        validate(False)


def decode_plan(body, document_id):
    validate(
        type(body) is dict
        and type(body.get("kind")) is str
        and body["kind"] in ("working", "pending")
    )
    pending = body["kind"] == "pending"
    v = wire._shape(
        body,
        (
            "kind",
            "document_id",
            "request_id",
            "handle" if pending else "expected_checkpoint_revision",
        ),
    )
    validate(wire._uuid(v["document_id"]) == document_id)
    result = dict(kind=v["kind"], document_id=document_id, request_id=wire._uuid(v["request_id"]))
    if pending:
        handle = _handle(v["handle"])
        validate(handle.document_id == document_id)
        result["handle"] = handle
    else:
        revision = wire._counter(v["expected_checkpoint_revision"])
        validate(revision >= 1)
        result["expected_checkpoint_revision"] = revision
    return result


def encode_plan(document_id, record, request_id):
    result = dict(kind=record.phase, document_id=str(document_id), request_id=str(request_id))
    if record.phase == "working":
        result["expected_checkpoint_revision"] = str(record.checkpoint_revision)
    else:
        h = SaveHandle(
            document_id,
            record.checkpoint_revision,
            record.base_storage_revision,
            record.base_sha256,
            record.working_sha256,
            len(record.working_data),
            record.metadata,
        )
        result["handle"] = dict(
            document_id=str(document_id),
            prepared_checkpoint_revision=str(h.prepared_checkpoint_revision),
            base_storage_revision=str(h.base_storage_revision),
            base_sha256=h.base_sha256,
            working_sha256=h.working_sha256,
            working_size_bytes=h.working_size_bytes,
            metadata=dict(
                selection=wire._selection_out(h.metadata.selection),
                origin=wire._origin(h.metadata.origin),
                pending=dict(operation_id=str(h.operation_id), request_sha256=h.request_sha256),
            ),
        )
    return wire._dump(result, 65536)
