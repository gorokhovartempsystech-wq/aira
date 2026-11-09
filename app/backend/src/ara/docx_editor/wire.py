"""Pure strict request decoding and explicit bounded metadata/projection JSON."""

import base64
import binascii
import re
from functools import wraps
from json import JSONEncoder
from uuid import UUID

from ara.docx_documents._dto import MAX_REVISION
from ara.docx_package.editor import Caret, CaretTarget, EditorSelection, SelectionTarget
from ara.docx_package.formatting import ParagraphFormat
from ara.docx_package.projection import SourceAnchor
from ara.docx_package.projection import _models as projection
from ara.docx_package.ranges import RangeEdit, TextPosition
from ara.docx_package.structure import DeleteParagraph, InsertParagraph

from . import _models
from ._commands import EditorCommand
from ._errors import error, native_errors, validate


def _shape(value, required, optional=()):
    validate(
        type(value) is dict
        and len(value) <= len(required) + len(optional)
        and all(type(k) is str for k in value)
        and set(required) <= value.keys()
        and value.keys() <= set(required) | set(optional)
    )
    return value


def _uuid(value):
    validate(type(value) is str and len(value) == 36)
    try:
        result = UUID(value)
    except ValueError:
        error("validation_error", 422)
    validate(str(result) == value)
    return result


def _counter(value):
    validate(
        type(value) is str
        and 1 <= len(value) <= 19
        and re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is not None
    )
    result = int(value)
    validate(result <= MAX_REVISION)
    return result


def _int(value, maximum=2147483647):
    validate(type(value) is int and 0 <= value <= maximum)
    return value


def _str(value, maximum, budget=None, key=None):
    validate(type(value) is str and len(value) <= maximum)
    if budget is not None:
        budget[key] += len(value)
        validate(budget[key] <= 1000000)
    return value


def _anchor(value):
    v = _shape(value, ("source_sha256", "part_name", "path"))
    validate(type(v["path"]) is list and 1 <= len(v["path"]) <= 128)
    from ._commands import _anchor as checked

    return checked(
        SourceAnchor(v["source_sha256"], v["part_name"], tuple(_int(i, 100000) for i in v["path"]))
    )


def _caret(value, target=False):
    first = "block_index" if target else "anchor"
    v = _shape(value, (first, "offset"), ("affinity",))
    head = _int(v[first]) if target else _anchor(v[first])
    affinity = v.get("affinity", "right")
    validate(type(affinity) is str and affinity in ("left", "right"))
    return (CaretTarget if target else Caret)(head, _int(v["offset"]), affinity)


def _selection(value, target=False):
    v = _shape(value, ("anchor", "focus"))
    return (SelectionTarget if target else EditorSelection)(
        _caret(v["anchor"], target), _caret(v["focus"], target)
    )


def _position(value):
    v = _shape(value, ("anchor", "offset"))
    return TextPosition(_anchor(v["anchor"]), _int(v["offset"]))


def _batch(value, action):
    validate(type(value) is list and len(value) <= 1000)
    budget = {"expected": 0, "text": 0, "paragraphs": 0}
    result = []
    for item in value:
        if action == "range_edit":
            v = _shape(item, ("start", "end", "expected_text", "replacement_text"))
            expected = _str(v["expected_text"], 1000000, budget, "expected")
            replacement = _str(v["replacement_text"], 1000000, budget, "text")
            result.append(
                RangeEdit(_position(v["start"]), _position(v["end"]), expected, replacement)
            )
        elif action == "format":
            v = _shape(item, ("anchor", "expected_text"), ("style_id", "list_kind", "list_id"))
            expected = _str(v["expected_text"], 1000000, budget, "expected")
            style, kind, identity = v.get("style_id"), v.get("list_kind", "none"), v.get("list_id")
            if style is not None:
                _str(style, 255)
            if identity is not None:
                _str(identity, 10)
            result.append(ParagraphFormat(_anchor(v["anchor"]), expected, style, kind, identity))
        else:
            validate(type(item) is dict and type(item.get("kind")) is str)
            if item["kind"] == "delete":
                v = _shape(item, ("kind", "anchor", "expected_text"))
                result.append(
                    DeleteParagraph(
                        _anchor(v["anchor"]), _str(v["expected_text"], 1000000, budget, "expected")
                    )
                )
            else:
                v = _shape(item, ("kind", "anchor", "expected_text"), ("texts", "position"))
                validate(v["kind"] == "insert")
                texts = v.get("texts", [""])
                validate(type(texts) is list and 1 <= len(texts) <= 1000)
                budget["paragraphs"] += len(texts)
                validate(budget["paragraphs"] <= 1000)
                expected = _str(v["expected_text"], 1000000, budget, "expected")
                texts = tuple(_str(t, 1000000, budget, "text") for t in texts)
                result.append(
                    InsertParagraph(
                        _anchor(v["anchor"]), expected, texts, v.get("position", "after")
                    )
                )
    return tuple(result)


def decode_open(value):
    v = _shape(
        value,
        (
            "registry_id",
            "client_open_id",
            "expected_open_sequence",
            "expected_checkpoint_revision",
            "mode",
        ),
    )
    validate(type(v["mode"]) is str and v["mode"] in ("current", "recover"))
    return dict(
        registry_id=_uuid(v["registry_id"]),
        client_open_id=_uuid(v["client_open_id"]),
        expected_open_sequence=_counter(v["expected_open_sequence"]),
        expected_checkpoint_revision=_counter(v["expected_checkpoint_revision"]),
        mode=v["mode"],
    )


def _identity(value, extra=()):
    v = _shape(
        value, ("command_id", "expected_command_sequence", "expected_session_revision"), extra
    )
    return dict(
        command_id=_uuid(v["command_id"]),
        expected_command_sequence=_counter(v["expected_command_sequence"]),
        expected_session_revision=_counter(v["expected_session_revision"]),
    )


def decode_control(value, *, close=False):
    validate(type(close) is bool)
    result = _identity(value, ("mode",) if close else ())
    if close:
        mode = value.get("mode", "checkpoint")
        validate(type(mode) is str and mode in ("checkpoint", "release_local"))
        result["mode"] = mode
    return result


def decode_command(value):
    result = _identity(value, ("command",))
    validate("command" in value)
    v = _shape(value["command"], ("action",), ("value", "after"))
    action = v["action"]
    from ._commands import ACTIONS

    validate(type(action) is str and action in ACTIONS)
    data, after = v.get("value"), v.get("after")
    with native_errors():
        if action == "capture":
            data = _selection(data)
        elif action == "insert_table":
            from ara.docx_package.editor._objects import TableSize

            size = _shape(data, ("rows", "columns"))
            data = TableSize(_int(size["rows"], 100), _int(size["columns"], 32))
        elif action == "insert_image":
            from ara.docx_package.editor._images import MAX_BASE64, ImageData

            image = _shape(data, ("data_base64",), ("alt_text",))
            encoded = _str(image["data_base64"], MAX_BASE64)
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                error("validation_error", 422)
            validate(base64.b64encode(raw).decode("ascii") == encoded)
            data = ImageData(raw, image.get("alt_text", ""))
        elif action in ("insert_text", "paste_text"):
            data = _str(data, 100000 if action == "insert_text" else 1000000)
            validate(
                all(
                    ord(c) in (9, 10, 13)
                    or 0x20 <= ord(c) <= 0xD7FF
                    or 0xE000 <= ord(c) <= 0xFFFD
                    or 0x10000 <= ord(c) <= 0x10FFFF
                    for c in data
                )
            )
        elif action in ("range_edit", "structure", "format"):
            data = _batch(data, action)
        if after is not None:
            after = _selection(after, True)
        result["command"] = EditorCommand(action, data, after)
    return result


def _output(method):
    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            from ara.documents.storage import DocumentError

            if isinstance(exc, DocumentError):
                raise
            error("editor_error", 500)

    return call


def _large():
    from ara.documents.storage import DocumentError

    raise DocumentError(
        413, "editor_reply_limit_exceeded", "Editor reply exceeds a technical limit"
    )


def _dump(value, maximum):
    result = bytearray()
    for chunk in JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False).iterencode(
        value
    ):
        data = chunk.encode("utf-8")
        if len(result) + len(data) > maximum:
            _large()
        result.extend(data)
    return bytes(result)


def _anchor_out(value):
    return dict(source_sha256=value.source_sha256, part_name=value.part_name, path=list(value.path))


def _caret_out(value):
    return dict(anchor=_anchor_out(value.anchor), offset=value.offset, affinity=value.affinity)


def _selection_out(value):
    return dict(anchor=_caret_out(value.anchor), focus=_caret_out(value.focus))


def _origin(value):
    return dict(
        session_id=str(value.session_id),
        session_revision=str(value.session_revision),
        position_id=str(value.position_id),
    )


def _summary(value):
    value.__post_init__()
    if not 1 <= value.current_size_bytes <= 33554432:
        raise ValueError("Invalid DOCX summary size")
    return dict(
        document_id=str(value.document_id),
        title=value.title,
        storage_revision=str(value.storage_revision),
        current_sha256=value.current_sha256,
        current_size_bytes=value.current_size_bytes,
        created_at=value.created_at.isoformat(),
        updated_at=value.updated_at.isoformat(),
    )


def _last(value):
    if value is None:
        return None
    return dict(
        command_id=str(value.command_id),
        request_sha256=value.request_sha256,
        action=value.action,
        expected_command_sequence=str(value.expected_command_sequence),
        expected_session_revision=str(value.expected_session_revision),
        result_command_sequence=str(value.result_command_sequence),
        result_session_revision=str(value.result_session_revision),
        result_position_id=str(value.result_position_id),
    )


def _active(value):
    if value is None:
        return None
    return dict(
        command_id=str(value.command_id),
        action=value.action,
        request_sha256=value.request_sha256,
        expected_command_sequence=str(value.expected_command_sequence),
        expected_session_revision=str(value.expected_session_revision),
        stage=value.stage,
        operation_id=str(value.operation_id) if value.operation_id else None,
        save_state=value.save_state,
    )


def _reply(value):
    if type(value) not in (
        _models.EditorView,
        _models.OpenedEditor,
        _models.RecoveryView,
        _models.ClosedEditor,
    ):
        raise ValueError("Unknown editor reply")
    value.__post_init__()
    if type(value) is _models.OpenedEditor:
        return dict(
            kind="opened",
            view=_reply(value.view),
            accepted_open_sequence=str(value.accepted_open_sequence),
            next_open_sequence=str(value.next_open_sequence),
        )
    if type(value) is _models.ClosedEditor:
        return dict(
            kind="closed",
            registry_id=str(value.registry_id),
            document_id=str(value.document_id),
            session_id=str(value.session_id),
            mode=value.mode,
            checkpoint_revision=str(value.checkpoint_revision)
            if value.checkpoint_revision is not None
            else None,
        )
    if type(value) is _models.RecoveryView:
        return dict(
            kind="recovery",
            registry_id=str(value.registry_id),
            open_sequence=str(value.open_sequence),
            document=_summary(value.document),
            checkpoint_revision=str(value.checkpoint_revision),
            phase=value.phase,
            base_storage_revision=str(value.base_storage_revision)
            if value.base_storage_revision is not None
            else None,
            base_sha256=value.base_sha256,
            working_sha256=value.working_sha256,
            working_size_bytes=value.working_size_bytes,
            selection=_selection_out(value.selection) if value.selection else None,
            origin=_origin(value.origin) if value.origin else None,
            pending_status=value.pending_status,
            operation_id=str(value.operation_id) if value.operation_id else None,
        )
    d = value.editor.document
    return dict(
        kind="editor",
        registry_id=str(value.registry_id),
        document_id=str(value.document_id),
        session_id=str(value.session_id),
        command_sequence=str(value.command_sequence),
        base_storage_revision=str(value.base_storage_revision),
        base_sha256=value.base_sha256,
        checkpoint_revision=str(value.checkpoint_revision),
        observed_current=_summary(value.observed_current),
        observed_checkpoint_revision=str(value.observed_checkpoint_revision),
        observed_checkpoint_phase=value.observed_checkpoint_phase,
        state=value.state,
        recovery_operation_id=str(value.recovery_operation_id)
        if value.recovery_operation_id
        else None,
        last_command=_last(value.last_command),
        active_command=_active(value.active_command),
        position_id=str(value.editor.position_id),
        selection=_selection_out(value.editor.selection),
        document=dict(
            session_revision=str(d.revision),
            source_sha256=d.projection.source.sha256,
            main_part=d.projection.source.main_part,
            size_bytes=len(d.data),
            is_dirty=d.is_dirty,
            undo_depth=d.undo_depth,
            redo_depth=d.redo_depth,
        ),
    )


@_output
def encode_reply(value):
    return _dump(_reply(value), 65536)


_FIELDS = {
    SourceAnchor: ("source_sha256", "part_name", "path"),
    projection.Hyperlink: ("anchor", "relationship_id", "bookmark"),
    projection.Span: (
        "kind",
        "anchor",
        "run_anchor",
        "text",
        "start",
        "end",
        "xml_space",
        "break_type",
        "hyperlink",
        "reason",
    ),
    projection.Paragraph: (
        "kind",
        "anchor",
        "text",
        "spans",
        "properties_anchor",
        "style_id",
        "numbering_id",
        "numbering_level",
        "has_opaque",
    ),
    projection.OpaqueBlock: ("kind", "anchor", "reason", "element_name"),
    projection.Cell: ("anchor", "blocks", "properties_anchor", "grid_span", "vertical_merge"),
    projection.Row: ("anchor", "cells", "properties_anchor"),
    projection.Table: ("kind", "anchor", "rows", "properties_anchor"),
    projection.Notice: ("code", "part_name", "anchor"),
}


@_output
def encode_projection(value, *, compact=False):
    if type(value) is not _models.EditorView or type(compact) is not bool:
        raise ValueError("Invalid editor projection")
    meta = _reply(value)
    p = value.editor.document.projection
    records, characters = 0, 0

    def wire(item, depth=0):
        nonlocal records, characters
        if depth > 128:
            _large()
        if item is None or type(item) in (bool, int):
            return item
        if type(item) is str:
            characters += len(item)
            if characters > 1000000:
                _large()
            return item
        if type(item) is tuple:
            return [wire(v, depth + 1) for v in item]
        names = _FIELDS.get(type(item))
        if names is None:
            raise ValueError("Unknown projection record")
        records += 1
        if records > (20000 if compact else 5000):
            _large()
        if compact and type(item) is projection.Paragraph:
            names = tuple(name for name in names if name != "spans")
            result = {name: wire(getattr(item, name), depth + 1) for name in names}
            records += len(item.spans)
            if records > 20000:
                _large()
            # Exact edit coordinates without duplicating text, hashes and run metadata.
            result["edit_spans"] = [
                dict(kind=s.kind, path=list(s.anchor.path), start=s.start, end=s.end)
                for s in item.spans
            ]
            return result
        return {name: wire(getattr(item, name), depth + 1) for name in names}

    payload = dict(
        source_sha256=p.source.sha256,
        main_part=p.source.main_part,
        body_anchor=wire(p.body_anchor),
        coverage_scope=p.coverage_scope,
        has_unprojected_content=p.has_unprojected_content,
        blocks=wire(p.blocks),
        notices=wire(p.notices),
    )
    return _dump(dict(kind="editor_projection", view=meta, projection=payload), 8 * 1024 * 1024)
