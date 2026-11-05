"""Frozen D03-16B2A: source-bound checkpoint metadata without lossy coercion."""

import importlib
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from uuid import UUID

import pytest

from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.editor import Caret, EditorError, EditorSelection, EditorSession


def api():
    return importlib.import_module("ara.docx_package.checkpoint")


def sample(pending=False, revision=0):
    raw = create_docx((NewParagraph("A😀е\u0301"), NewParagraph("Tail")))
    e = EditorSession(raw)
    blocks = e.snapshot().document.projection.blocks
    selected = EditorSelection(Caret(blocks[1].anchor, 2, "left"), Caret(blocks[0].anchor, 1))
    assert e.capture(selected, expected_revision=0).selection == selected
    origin = {
        "session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "session_revision": str(revision),
        "position_id": "0",
    }
    wire_selection = asdict(selected)
    for c in wire_selection.values():
        c["anchor"]["path"] = list(c["anchor"]["path"])
    wire = {"selection": wire_selection, "origin": origin, "pending": None}
    if pending:
        wire["pending"] = {
            "operation_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "request_sha256": "c" * 64,
        }
    return raw, selected, wire


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("revision", [0, 9223372036854775807])
def test_exact_json_roundtrip_and_typed_identities(pending, revision):
    raw, selected, wire = sample(pending, revision)
    a = api()
    phase = "pending" if pending else "working"
    decoded = a.decode_metadata(wire, data=raw, saved_sha256="0" * 64, phase=phase)
    assert decoded.selection == selected
    assert decoded.origin.session_id == UUID(wire["origin"]["session_id"])
    assert decoded.origin.session_revision == revision
    assert (
        a.encode_metadata(decoded, data=raw, saved_sha256=sha256(raw).hexdigest(), phase=phase)
        == wire
    )
    if pending:
        assert decoded.pending.operation_id == UUID(wire["pending"]["operation_id"])
        assert decoded.pending.request_sha256 == "c" * 64
    else:
        assert decoded.pending is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_revision", 0),
        ("session_revision", True),
        ("session_revision", "01"),
        ("session_revision", "-1"),
        ("session_revision", "9223372036854775808"),
        ("position_id", "1.0"),
        ("session_id", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
        ("session_id", None),
    ],
)
def test_origin_rejects_lossy_or_noncanonical_values(field, value):
    raw, _, wire = sample()
    wire["origin"][field] = value
    with pytest.raises(api().CheckpointError) as caught:
        api().decode_metadata(wire, data=raw, saved_sha256="0" * 64, phase="working")
    assert caught.value.code == "invalid_input"


@pytest.mark.parametrize(
    "case", ["missing", "unknown", "offset", "path", "affinity", "pending", "phase"]
)
def test_schema_is_exact_and_phase_bound(case):
    raw, _, wire = sample()
    phase = "working"
    if case == "missing":
        del wire["pending"]
    if case == "unknown":
        wire["extra"] = "SYNTHETIC_PRIVATE" * 100000
    if case == "offset":
        wire["selection"]["anchor"]["offset"] = True
    if case == "path":
        wire["selection"]["anchor"]["anchor"]["path"] = [True]
    if case == "affinity":
        wire["selection"]["focus"]["affinity"] = "auto"
    if case == "pending":
        wire["pending"] = {"operation_id": "b" * 32, "request_sha256": "c" * 64}
    if case == "phase":
        phase = "empty"
    with pytest.raises(api().CheckpointError) as caught:
        api().decode_metadata(wire, data=raw, saved_sha256="0" * 64, phase=phase)
    assert caught.value.code == "invalid_input"
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


def test_decoder_and_encoder_bind_selection_to_actual_working_bytes():
    raw, _, wire = sample()
    wire["selection"]["focus"]["anchor"]["source_sha256"] = "0" * 64
    with pytest.raises(EditorError) as caught:
        api().decode_metadata(wire, data=raw, saved_sha256="0" * 64, phase="working")
    assert caught.value.code == "stale_selection"


def test_nested_mutation_never_changes_the_input_or_output_of_another_call():
    raw, _, wire = sample()
    original = deepcopy(wire)
    a = api()
    decoded = a.decode_metadata(wire, data=raw, saved_sha256="0" * 64, phase="working")
    wire["selection"]["focus"]["anchor"]["path"].append(999)
    encoded = a.encode_metadata(decoded, data=raw, saved_sha256="0" * 64, phase="working")
    assert encoded == original
    object.__setattr__(decoded.origin, "session_revision", True)
    with pytest.raises(a.CheckpointError):
        a.encode_metadata(decoded, data=raw, saved_sha256="0" * 64, phase="working")
    assert encoded == original


def test_public_records_validate_types_without_implicit_conversions():
    a = api()
    raw, selection, _ = sample()
    origin = a.CheckpointOrigin(UUID("a" * 32), 0, 0)
    value = a.CheckpointMetadata(selection, origin)
    assert (
        a.encode_metadata(value, data=raw, saved_sha256="0" * 64, phase="working")["pending"]
        is None
    )
    with pytest.raises(a.CheckpointError):
        a.CheckpointOrigin(str(origin.session_id), 0, 0)
    with pytest.raises(a.CheckpointError):
        a.PendingSave(UUID("b" * 32), "A" * 64)
