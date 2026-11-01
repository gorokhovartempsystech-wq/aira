"""Frozen E1: strict native JSON mapping and content-free metadata replies."""

import importlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from docx_storage_fixtures import raw
from test_docx_checkpoints import reject

from ara.docx_documents._dto import MAX_REVISION, DocxSummary
from ara.docx_editor._models import ClosedEditor, EditorView, OpenedEditor, RecoveryView
from ara.docx_package.editor import EditorSession
from ara.docx_package.formatting import ParagraphFormat
from ara.docx_package.ranges import RangeEdit
from ara.docx_package.structure import DeleteParagraph, InsertParagraph


def api():
    return importlib.import_module("ara.docx_editor.wire")


def view(data=None):
    data = raw("SYNTHETIC_PRIVATE_BODY 🧪") if data is None else data
    snapshot = EditorSession(data).snapshot()
    document = uuid4()
    current = DocxSummary(
        document,
        "Synthetic",
        1,
        sha256(data).hexdigest(),
        len(data),
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    return EditorView(
        uuid4(),
        document,
        uuid4(),
        0,
        snapshot,
        1,
        current.current_sha256,
        1,
        current,
        1,
        "empty",
        "editable",
        None,
    )


def identity():
    return dict(
        command_id=str(uuid4()), expected_command_sequence="0", expected_session_revision="0"
    )


def anchor(snapshot):
    a = snapshot.editor.selection.anchor.anchor
    return dict(source_sha256=a.source_sha256, part_name=a.part_name, path=list(a.path))


def test_open_and_control_identity_are_canonical():
    registry, key = uuid4(), uuid4()
    decoded = api().decode_open(
        dict(
            registry_id=str(registry),
            client_open_id=str(key),
            expected_open_sequence=str(MAX_REVISION),
            expected_checkpoint_revision="0",
            mode="recover",
        )
    )
    assert decoded["registry_id"] == registry and decoded["client_open_id"] == key
    assert (
        decoded["expected_open_sequence"] == MAX_REVISION
        and decoded["expected_checkpoint_revision"] == 0
    )
    decoded = api().decode_control({**identity(), "mode": "release_local"}, close=True)
    assert decoded["mode"] == "release_local" and decoded["expected_command_sequence"] == 0
    reject(
        lambda: api().decode_control({**identity(), "mode": "release_local"}),
        "validation_error",
        422,
    )


@pytest.mark.parametrize("counter", [0, True, 1.0, "00", "01", "+1", " 1", str(2**63), "-1", "1e2"])
def test_noncanonical_counter_is_rejected(counter):
    reject(
        lambda: api().decode_control({**identity(), "expected_command_sequence": counter}),
        "validation_error",
        422,
    )


def test_command_defaults_and_selection_are_exact_native_records():
    source = view()
    a = anchor(source)
    caret = dict(anchor=a, offset=2)
    command = api().decode_command(
        {**identity(), "command": dict(action="capture", value=dict(anchor=caret, focus=caret))}
    )["command"]
    assert command.value.anchor.offset == 2 and command.value.anchor.affinity == "right"
    assert command.value.anchor.anchor.path == tuple(a["path"])
    request = {**identity(), "command": dict(action="paste_text", value="One\r\nTwo 🧪")}
    assert api().decode_command(request)["command"].value == "One\r\nTwo 🧪"
    assert (
        api().decode_command({**identity(), "command": {"action": "undo"}})["command"].value is None
    )


@pytest.mark.parametrize("action", ["range_edit", "structure", "format"])
def test_native_batch_mapping_preserves_payload_and_defaults(action):
    source = view()
    a = anchor(source)
    after = dict(anchor=dict(block_index=0, offset=0), focus=dict(block_index=0, offset=0))
    if action == "range_edit":
        record = dict(
            start=dict(anchor=a, offset=0),
            end=dict(anchor=a, offset=1),
            expected_text="S",
            replacement_text="T",
        )
        values = [record]
    elif action == "structure":
        values = [
            dict(kind="insert", anchor=a, expected_text="x"),
            dict(kind="delete", anchor=a, expected_text="x"),
        ]
    else:
        values = [dict(anchor=a, expected_text="x", style_id="Heading2")]
    decoded = api().decode_command(
        {**identity(), "command": dict(action=action, value=values, after=after)}
    )["command"]
    if action == "range_edit":
        assert type(decoded.value[0]) is RangeEdit
    elif action == "structure":
        assert type(decoded.value[0]) is InsertParagraph and decoded.value[0].texts == ("",)
        assert type(decoded.value[1]) is DeleteParagraph
    else:
        assert type(decoded.value[0]) is ParagraphFormat and decoded.value[0].list_kind == "none"
    assert decoded.after.anchor.block_index == 0


def test_unknown_fields_uuid_coercion_and_nested_shape_fail_before_native_copy():
    source = view()
    reject(
        lambda: api().decode_control({**identity(), "document_id": str(source.document_id)}),
        "validation_error",
        422,
    )
    reject(
        lambda: api().decode_control({**identity(), "command_id": str(uuid4()).upper()}),
        "validation_error",
        422,
    )
    a = anchor(source)
    a["path"] = [0] * 129
    caret = dict(anchor=a, offset=0)
    reject(
        lambda: api().decode_command(
            {**identity(), "command": dict(action="capture", value=dict(anchor=caret, focus=caret))}
        ),
        "validation_error",
        422,
    )
    reject(
        lambda: api().decode_command({**identity(), "command": {"action": "undo", "limits": {}}}),
        "validation_error",
        422,
    )


def test_metadata_reply_omits_body_and_binary_and_uses_string_counters():
    source = replace(view(), command_sequence=MAX_REVISION)
    payload = api().encode_reply(source)
    assert type(payload) is bytes and len(payload) <= 65536
    data = json.loads(payload)
    assert data["kind"] == "editor" and data["command_sequence"] == str(MAX_REVISION)
    assert data["document"]["session_revision"] == "0" and data["position_id"] == "0"
    assert data["observed_current"]["storage_revision"] == "1"
    assert data["selection"]["anchor"]["offset"] == 0
    assert "SYNTHETIC_PRIVATE_BODY" not in payload.decode()
    assert "blocks" not in data and "data" not in data["document"]
    assert "source" not in data["document"] and "original" not in payload.decode()
    assert data["document"]["size_bytes"] == len(source.editor.document.data)


def test_all_reply_kinds_have_explicit_shapes():
    source = view()
    opened = OpenedEditor(source, 0, 1)
    assert json.loads(api().encode_reply(opened))["next_open_sequence"] == "1"
    closed = ClosedEditor(
        source.registry_id, source.document_id, source.session_id, "release_local", None
    )
    assert json.loads(api().encode_reply(closed))["checkpoint_revision"] is None
    recovery = RecoveryView(
        source.registry_id,
        0,
        source.observed_current,
        0,
        "absent",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    result = json.loads(api().encode_reply(recovery))
    assert (
        result["kind"] == "recovery"
        and result["checkpoint_revision"] == "0"
        and result["origin"] is None
    )
    reject(lambda: api().encode_reply(source.editor), "editor_error", 500)


def test_rich_projection_includes_structure_not_source_package():
    source = view(Path("tests/fixtures/docx/rich-source.docx").read_bytes())
    payload = api().encode_projection(source)
    data = json.loads(payload)
    assert data["kind"] == "editor_projection"
    assert data["view"]["document_id"] == str(source.document_id)
    projection = data["projection"]
    assert projection["source_sha256"] == source.editor.document.projection.source.sha256
    assert projection["coverage_scope"] == "main-body-structural-v1"
    assert any(b["kind"] == "table" for b in projection["blocks"])
    assert projection["has_unprojected_content"] is True and projection["notices"]
    assert "_original" not in payload.decode() and "original_data" not in payload.decode()
    assert "Device classification" in payload.decode()


def test_projection_limits_refuse_instead_of_truncating():
    source = deepcopy(view())
    p = source.editor.document.projection.blocks[0]
    object.__setattr__(p, "text", "x" * 1000001)
    reject(lambda: api().encode_projection(source), "editor_reply_limit_exceeded", 413)
    source = deepcopy(view())
    p = source.editor.document.projection.blocks[0]
    object.__setattr__(source.editor.document.projection, "blocks", (p,) * 5001)
    reject(lambda: api().encode_projection(source), "editor_reply_limit_exceeded", 413)
