"""Validate bounded shapes before serialization; bind anchors through pure restore."""

import json
from uuid import UUID

from ..editor import Caret, EditorSelection, EditorSession
from ..projection import SourceAnchor
from ._models import (
    CheckpointError,
    CheckpointMetadata,
    CheckpointOrigin,
    PendingSave,
    digest,
    integer,
    require,
)


def _object(value, keys):
    require(type(value) is dict and len(value) == len(keys))
    require(all(type(k) is str for k in value) and set(value) == set(keys))
    return value


def _uuid(value):
    require(type(value) is str and len(value) == 36)
    try:
        parsed = UUID(value)
    except ValueError:
        raise CheckpointError("invalid_input") from None
    require(str(parsed) == value)
    return parsed


def _decimal(value):
    require(type(value) is str and 1 <= len(value) <= 19)
    require(all(c in "0123456789" for c in value) and (value == "0" or value[0] != "0"))
    return integer(int(value))


def _point(value):
    value = _object(value, ("anchor", "offset", "affinity"))
    anchor = _object(value["anchor"], ("source_sha256", "part_name", "path"))
    digest(anchor["source_sha256"])
    part, path = anchor["part_name"], anchor["path"]
    require(type(part) is str and 1 <= len(part) <= 1024)
    require("\x00" not in part and not any(0xD800 <= ord(c) <= 0xDFFF for c in part))
    require(type(path) is list and 1 <= len(path) <= 128)
    for index in path:
        integer(index, 100000)
    integer(value["offset"], 2147483647)
    require(type(value["affinity"]) is str and value["affinity"] in ("left", "right"))
    return Caret(
        SourceAnchor(anchor["source_sha256"], part, tuple(path)),
        value["offset"],
        value["affinity"],
    )


def _wire_point(caret):
    a = caret.anchor
    return {
        "anchor": {
            "source_sha256": a.source_sha256,
            "part_name": a.part_name,
            "path": list(a.path),
        },
        "offset": caret.offset,
        "affinity": caret.affinity,
    }


def encode_metadata(value, *, data, saved_sha256, phase):
    require(type(value) is CheckpointMetadata)
    value.__post_init__()
    require(type(phase) is str and phase in ("working", "pending"))
    require((phase == "pending") == (value.pending is not None))
    EditorSession.restore(data, saved_sha256=saved_sha256, selection=value.selection)
    wire = {
        "selection": {
            "anchor": _wire_point(value.selection.anchor),
            "focus": _wire_point(value.selection.focus),
        },
        "origin": {
            "session_id": str(value.origin.session_id),
            "session_revision": str(value.origin.session_revision),
            "position_id": str(value.origin.position_id),
        },
        "pending": None
        if value.pending is None
        else {
            "operation_id": str(value.pending.operation_id),
            "request_sha256": value.pending.request_sha256,
        },
    }
    for options in ({"ensure_ascii": True, "separators": (",", ":")}, {"ensure_ascii": False}):
        if len(json.dumps(wire, sort_keys=True, **options).encode("utf-8")) > 65536:
            raise CheckpointError("checkpoint_limit_exceeded")
    return wire


def decode_metadata(value, *, data, saved_sha256, phase):
    value = _object(value, ("selection", "origin", "pending"))
    selected = _object(value["selection"], ("anchor", "focus"))
    selection = EditorSelection(_point(selected["anchor"]), _point(selected["focus"]))
    origin = _object(value["origin"], ("session_id", "session_revision", "position_id"))
    origin = CheckpointOrigin(
        _uuid(origin["session_id"]),
        _decimal(origin["session_revision"]),
        _decimal(origin["position_id"]),
    )
    pending = value["pending"]
    if pending is not None:
        pending = _object(pending, ("operation_id", "request_sha256"))
        pending = PendingSave(_uuid(pending["operation_id"]), digest(pending["request_sha256"]))
    result = CheckpointMetadata(selection, origin, pending)
    encode_metadata(result, data=data, saved_sha256=saved_sha256, phase=phase)
    return result
