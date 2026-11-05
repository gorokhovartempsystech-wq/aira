"""Independent positive acceptance for the in-memory DOCX editing session."""

from dataclasses import FrozenInstanceError, fields, is_dataclass
from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pytest
from docx_editing_fixtures import MAIN, text_spans, zip_parts
from docx_projection_fixtures import package
from test_docx_ranges import change, formatted_paragraph

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/docx/rich-source.docx"


def api():
    # Collect before the implementation exists; missing API must fail tests.
    return import_module("ara.docx_package.session")


def original_api():
    return import_module("ara.docx_package")


def ranges_api():
    return import_module("ara.docx_package.ranges")


def request(snapshot, replacement, *, index=0, start=0, end=None):
    span = text_spans(snapshot.projection)[index]
    finish = len(span.text) if end is None else end
    return change(span, start, span, finish, span.text[start:finish], replacement)


def state(snapshot):
    return (
        snapshot.revision,
        snapshot.data,
        snapshot.is_dirty,
        snapshot.undo_depth,
        snapshot.redo_depth,
    )


def assert_snapshot(snapshot, data, *, revision, undo, redo, dirty):
    assert isinstance(snapshot, api().SessionSnapshot)
    assert type(snapshot.data) is bytes
    assert type(snapshot.revision) is int and snapshot.revision >= 0
    assert type(snapshot.undo_depth) is int and snapshot.undo_depth >= 0
    assert type(snapshot.redo_depth) is int and snapshot.redo_depth >= 0
    assert type(snapshot.is_dirty) is bool
    assert state(snapshot) == (revision, data, dirty, undo, redo)
    digest = sha256(data).hexdigest()
    assert snapshot.projection.source.sha256 == digest
    assert snapshot.projection.source.size_bytes == len(data)
    assert original_api().export_original(snapshot.projection.source) == data
    assert all(span.anchor.source_sha256 == digest for span in text_spans(snapshot.projection))


def fixture_session(*texts, **options):
    raw, _ = package(formatted_paragraph(*(texts or ("alpha beta",))))
    return raw, api().DocxSession(raw, **options)


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_open_preserves_exact_package_and_exposes_authoritative_initial_snapshot(strict, encoding):
    raw, _ = package(
        formatted_paragraph("Реле 😀", " and sensor"),
        main_part="custom/Requirements.XML",
        strict=strict,
        encoding=encoding,
        comment=b"original PK\x05\x06 comment",
    )
    session = api().DocxSession(raw)
    snapshot = session.snapshot()
    assert_snapshot(snapshot, raw, revision=0, undo=0, redo=0, dirty=False)
    assert snapshot.projection.source.main_part == "custom/Requirements.XML"
    assert [span.text for span in text_spans(snapshot.projection)] == ["Реле 😀", " and sensor"]
    assert state(session.snapshot()) == state(snapshot)


def test_snapshot_and_limits_are_frozen_slotted_with_safe_representations():
    private_text = "SYNTHETIC_SESSION_CONTENT_9135"
    raw, session = fixture_session(private_text)
    snapshot = session.snapshot()
    limits = api().SessionLimits()
    assert is_dataclass(snapshot) and is_dataclass(limits)
    assert tuple(field.name for field in fields(snapshot)) == (
        "revision",
        "data",
        "projection",
        "is_dirty",
        "undo_depth",
        "redo_depth",
    )
    assert not hasattr(snapshot, "__dict__") and not hasattr(limits, "__dict__")
    assert (limits.max_history_states, limits.max_history_bytes) == (100, 134217728)
    representations = (repr(snapshot), repr(session))
    assert all(private_text not in value and repr(raw) not in value for value in representations)
    assert all("DocxProjection(" not in value for value in representations)
    with pytest.raises(FrozenInstanceError):
        snapshot.revision = 90
    with pytest.raises(FrozenInstanceError):
        snapshot.data = b"replacement"
    with pytest.raises(FrozenInstanceError):
        limits.max_history_states = 1


def test_sequential_ranges_use_fresh_anchors_and_return_new_snapshots():
    raw, session = fixture_session("abcdef")
    initial = session.snapshot()
    first_request = request(initial, "XYZ", start=1, end=3)
    expected_first = ranges_api().export_docx_ranges(raw, (first_request,))
    first = session.apply((first_request,), expected_revision=0)
    assert_snapshot(first, expected_first, revision=1, undo=1, redo=0, dirty=True)
    assert text_spans(first.projection)[0].text == "aXYZdef"
    second_request = request(first, "!", start=4, end=6)
    expected_second = ranges_api().export_docx_ranges(first.data, (second_request,))
    second = session.apply((second_request,), expected_revision=1)
    assert_snapshot(second, expected_second, revision=2, undo=2, redo=0, dirty=True)
    assert text_spans(second.projection)[0].text == "aXYZ!f"
    assert first_request.start.anchor.source_sha256 != second_request.start.anchor.source_sha256
    assert_snapshot(initial, raw, revision=0, undo=0, redo=0, dirty=False)
    assert_snapshot(first, expected_first, revision=1, undo=1, redo=0, dirty=True)


def test_undo_redo_restores_exact_bytes_with_monotonically_increasing_revision():
    raw, session = fixture_session("one")
    first = session.apply((request(session.snapshot(), "two"),), expected_revision=0)
    second = session.apply((request(first, "three"),), expected_revision=1)
    assert_snapshot(
        session.undo(expected_revision=2), first.data, revision=3, undo=1, redo=1, dirty=True
    )
    assert_snapshot(session.undo(expected_revision=3), raw, revision=4, undo=0, redo=2, dirty=False)
    assert_snapshot(
        session.redo(expected_revision=4), first.data, revision=5, undo=1, redo=1, dirty=True
    )
    assert_snapshot(
        session.redo(expected_revision=5), second.data, revision=6, undo=2, redo=0, dirty=True
    )
    assert_snapshot(second, second.data, revision=2, undo=2, redo=0, dirty=True)


def test_mark_saved_is_idempotent_and_does_not_change_revision_or_history():
    raw, session = fixture_session("before")
    initial = session.mark_saved(expected_revision=0)
    assert_snapshot(initial, raw, revision=0, undo=0, redo=0, dirty=False)
    changed = session.apply((request(initial, "after"),), expected_revision=0)
    saved = session.mark_saved(expected_revision=1)
    assert_snapshot(saved, changed.data, revision=1, undo=1, redo=0, dirty=False)
    assert state(session.mark_saved(expected_revision=1)) == state(saved)
    assert_snapshot(changed, changed.data, revision=1, undo=1, redo=0, dirty=True)


def test_dirty_flag_recognizes_new_saved_content_after_undo_and_redo():
    raw, session = fixture_session("original")
    edited = session.apply((request(session.snapshot(), "saved edit"),), expected_revision=0)
    session.mark_saved(expected_revision=1)
    assert_snapshot(session.undo(expected_revision=1), raw, revision=2, undo=0, redo=1, dirty=True)
    assert_snapshot(
        session.redo(expected_revision=2), edited.data, revision=3, undo=1, redo=0, dirty=False
    )
    newer = session.apply((request(session.snapshot(), "newer edit"),), expected_revision=3)
    assert_snapshot(newer, newer.data, revision=4, undo=2, redo=0, dirty=True)
    assert_snapshot(
        session.undo(expected_revision=4), edited.data, revision=5, undo=1, redo=1, dirty=False
    )


def test_saving_after_undo_keeps_redo_and_moves_only_the_saved_marker():
    raw, session = fixture_session("start")
    first = session.apply((request(session.snapshot(), "middle"),), expected_revision=0)
    last = session.apply((request(first, "future"),), expected_revision=1)
    middle = session.undo(expected_revision=2)
    saved = session.mark_saved(expected_revision=3)
    assert_snapshot(saved, middle.data, revision=3, undo=1, redo=1, dirty=False)
    assert_snapshot(
        session.redo(expected_revision=3), last.data, revision=4, undo=2, redo=0, dirty=True
    )
    assert_snapshot(
        session.undo(expected_revision=4), first.data, revision=5, undo=1, redo=1, dirty=False
    )
    assert_snapshot(session.undo(expected_revision=5), raw, revision=6, undo=0, redo=2, dirty=True)


def test_real_edit_after_undo_replaces_future_branch_without_mutating_old_snapshots():
    raw, session = fixture_session("root")
    first = session.apply((request(session.snapshot(), "common"),), expected_revision=0)
    discarded = session.apply((request(first, "discarded future"),), expected_revision=1)
    base = session.undo(expected_revision=2)
    branch = session.apply((request(base, "new branch"),), expected_revision=3)
    assert_snapshot(branch, branch.data, revision=4, undo=2, redo=0, dirty=True)
    assert text_spans(branch.projection)[0].text == "new branch"
    assert text_spans(discarded.projection)[0].text == "discarded future"
    assert_snapshot(
        session.undo(expected_revision=4), first.data, revision=5, undo=1, redo=1, dirty=True
    )
    assert_snapshot(
        session.redo(expected_revision=5), branch.data, revision=6, undo=2, redo=0, dirty=True
    )
    assert_snapshot(base, first.data, revision=3, undo=1, redo=1, dirty=True)
    assert raw != discarded.data and discarded.data != branch.data


@pytest.mark.parametrize("noop_kind", ["empty", "equal", "compensating"])
def test_noop_preserves_revision_dirty_marker_and_redo_branch(noop_kind):
    raw, session = fixture_session("aaaa")
    changed = session.apply((request(session.snapshot(), "future"),), expected_revision=0)
    session.mark_saved(expected_revision=1)
    current = session.undo(expected_revision=1)
    if noop_kind == "empty":
        edits = ()
    elif noop_kind == "equal":
        edits = (request(current, "aaaa"),)
    else:
        edits = (request(current, "aa", start=0, end=1), request(current, "", start=1, end=2))
        assert ranges_api().export_docx_ranges(raw, edits) == raw
    result = session.apply(edits, expected_revision=2)
    assert_snapshot(result, raw, revision=2, undo=0, redo=1, dirty=True)
    assert state(result) == state(current)
    assert_snapshot(
        session.redo(expected_revision=2), changed.data, revision=3, undo=1, redo=0, dirty=False
    )


def test_noop_at_initial_saved_state_does_not_create_undo_history():
    raw, session = fixture_session("original")
    initial = session.snapshot()
    same = session.apply((request(initial, "original"),), expected_revision=0)
    assert_snapshot(same, raw, revision=0, undo=0, redo=0, dirty=False)
    assert_snapshot(
        session.apply((), expected_revision=0), raw, revision=0, undo=0, redo=0, dirty=False
    )


def test_dirty_compares_package_content_not_only_plain_paragraph_text():
    raw, session = fixture_session("ab", "cd")
    first = session.apply(
        (request(session.snapshot(), "", index=0, start=1, end=2),), expected_revision=0
    )
    redistributed = session.apply(
        (request(first, "b", index=1, start=0, end=0),), expected_revision=1
    )
    assert [span.text for span in text_spans(redistributed.projection)] == ["a", "bcd"]
    assert redistributed.projection.blocks[0].text == "abcd"
    assert redistributed.data != raw and redistributed.is_dirty is True
    session.undo(expected_revision=2)
    assert_snapshot(session.undo(expected_revision=3), raw, revision=4, undo=0, redo=2, dirty=False)


def test_two_sessions_with_identical_input_have_independent_history_saved_markers_and_revision():
    raw, first = fixture_session("shared input")
    second = api().DocxSession(raw)
    second_initial = second.snapshot()
    first_edit = first.apply((request(first.snapshot(), "first session"),), expected_revision=0)
    first.mark_saved(expected_revision=1)
    assert_snapshot(second.snapshot(), raw, revision=0, undo=0, redo=0, dirty=False)
    second_edit = second.apply((request(second_initial, "second session"),), expected_revision=0)
    assert_snapshot(first.snapshot(), first_edit.data, revision=1, undo=1, redo=0, dirty=False)
    assert_snapshot(second_edit, second_edit.data, revision=1, undo=1, redo=0, dirty=True)
    assert_snapshot(first.undo(expected_revision=1), raw, revision=2, undo=0, redo=1, dirty=True)
    assert_snapshot(second.undo(expected_revision=1), raw, revision=2, undo=0, redo=1, dirty=False)
    assert_snapshot(second_initial, raw, revision=0, undo=0, redo=0, dirty=False)


def test_empty_existing_span_can_be_edited_and_recovered_with_undo_redo():
    raw, session = fixture_session("left", "", "right")
    changed = session.apply(
        (request(session.snapshot(), " inserted ", index=1),), expected_revision=0
    )
    assert [span.text for span in text_spans(changed.projection)] == ["left", " inserted ", "right"]
    assert_snapshot(session.undo(expected_revision=1), raw, revision=2, undo=0, redo=1, dirty=False)
    assert_snapshot(
        session.redo(expected_revision=2), changed.data, revision=3, undo=1, redo=0, dirty=True
    )


def test_unicode_range_sequence_preserves_code_point_offsets_through_history():
    raw, session = fixture_session("A😀e\u0301ЖZ")
    initial = session.snapshot()
    changed = session.apply((request(initial, "⚙", start=1, end=4),), expected_revision=0)
    assert text_spans(changed.projection)[0].text == "A⚙ЖZ"
    other = session.apply((request(changed, "!", start=3, end=4),), expected_revision=1)
    assert text_spans(other.projection)[0].text == "A⚙Ж!"
    assert_snapshot(
        session.undo(expected_revision=2), changed.data, revision=3, undo=1, redo=1, dirty=True
    )
    assert_snapshot(session.undo(expected_revision=3), raw, revision=4, undo=0, redo=2, dirty=False)


def test_rich_source_session_matches_range_export_and_round_trips_exact_undo_redo():
    raw = FIXTURE.read_bytes()
    session = api().DocxSession(raw)
    initial = session.snapshot()
    phrase = initial.projection.blocks[4].spans
    link = next(span for span in text_spans(initial.projection) if span.hyperlink is not None)
    table = next(block for block in initial.projection.blocks if block.kind == "table")
    cell = table.rows[1].cells[0].blocks[0].spans[0]
    edits = (
        change(
            phrase[0], 9, phrase[2], 6, "keeps a stable canonical type even ", "retains its type "
        ),
        change(link, 0, link, 9, "Synthetic", "Example"),
        change(cell, 0, cell, 1, cell.text[:1], "Q"),
    )
    expected = ranges_api().export_docx_ranges(raw, edits)
    changed = session.apply(edits, expected_revision=0)
    assert_snapshot(changed, expected, revision=1, undo=1, redo=0, dirty=True)
    before_parts, after_parts = zip_parts(raw), zip_parts(changed.data)
    assert {key: value for key, value in before_parts.items() if key != MAIN} == {
        key: value for key, value in after_parts.items() if key != MAIN
    }
    assert_snapshot(session.undo(expected_revision=1), raw, revision=2, undo=0, redo=1, dirty=False)
    restored = session.redo(expected_revision=2)
    assert_snapshot(restored, expected, revision=3, undo=1, redo=0, dirty=True)
    assert_snapshot(
        session.mark_saved(expected_revision=3), expected, revision=3, undo=1, redo=0, dirty=False
    )
    assert_snapshot(initial, raw, revision=0, undo=0, redo=0, dirty=False)
    assert_snapshot(changed, expected, revision=1, undo=1, redo=0, dirty=True)
