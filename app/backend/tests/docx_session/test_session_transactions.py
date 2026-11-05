"""Independent synthetic transaction and retained-history checks for D02-05."""

import random
from dataclasses import fields
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pytest

from ara.docx_package import DocxError, DocxLimits
from ara.docx_package.projection import (
    DocxProjection,
    ProjectionError,
    ProjectionLimits,
    project_docx,
)
from ara.docx_package.ranges import RangeEdit, RangeError, TextPosition, export_docx_ranges
from ara.docx_package.session import DocxSession, SessionError, SessionLimits, SessionSnapshot

WML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def document(text="alpha"):
    """Construct a minimal, deterministic stored ZIP, independent of acceptance fixtures."""
    parts = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/main.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.document.main+xml"/></Types>'
        ),
        "_rels/.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="main" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="main.xml"/></Relationships>'
        ),
        "main.xml": (
            f'<w:document xmlns:w="{WML}"><w:body><w:p><w:r>'
            f'<w:t xml:space="preserve">{escape(text)}</w:t>'
            "</w:r></w:p></w:body></w:document>"
        ),
    }
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        for name, value in parts.items():
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            archive.writestr(info, value.encode())
    return stream.getvalue()


def request(data, replacement, expected=None):
    span = project_docx(data).blocks[0].spans[0]
    return RangeEdit(
        TextPosition(span.anchor, 0),
        TextPosition(span.anchor, len(span.text)),
        span.text if expected is None else expected,
        replacement,
    )


def apply_text(session, text):
    before = session.snapshot()
    return session.apply((request(before.data, text),), expected_revision=before.revision)


def branched_session():
    session = DocxSession(document())
    middle = apply_text(session, "middle")
    saved = apply_text(session, "saved future")
    session.mark_saved(expected_revision=saved.revision)
    before = session.undo(expected_revision=saved.revision)
    assert before.data == middle.data and before.is_dirty
    assert before.undo_depth == before.redo_depth == 1
    return session, before, saved


def command_call(session, before, command):
    if command == "apply":
        edits = (request(before.data, "new branch"),)
    elif command == "equal_apply":
        text = before.projection.blocks[0].spans[0].text
        edits = (request(before.data, text),)
    else:
        edits = ()
    if command.endswith("apply") or command == "apply":
        return lambda: session.apply(edits, expected_revision=before.revision)
    return lambda: getattr(session, command)(expected_revision=before.revision)


@pytest.mark.parametrize(
    "command", ["apply", "empty_apply", "equal_apply", "undo", "redo", "mark_saved"]
)
def test_each_projection_failure_leaves_entire_transaction_uncommitted(monkeypatch, command):
    # Count every projection construction, including the final authoritative reply.
    probe, before, _ = branched_session()
    operation = command_call(probe, before, command)
    original_init = DocxProjection.__init__
    constructions = []

    def record_projection(self, *args, **kwargs):
        constructions.append(1)
        original_init(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(DocxProjection, "__init__", record_projection)
        operation()
    assert constructions, "Each reply must prepare a fresh authoritative projection"

    for fail_at in range(len(constructions)):
        session, before, saved = branched_session()
        operation = command_call(session, before, command)
        seen = []
        failure = ProjectionError("projection_limit_exceeded")

        def fail_selected_projection(self, *args, **kwargs):
            seen.append(1)
            if len(seen) == fail_at + 1:
                raise failure
            original_init(self, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(DocxProjection, "__init__", fail_selected_projection)
            with pytest.raises(ProjectionError) as caught:
                operation()
            assert caught.value is failure
        assert session.snapshot() == before
        replay = session.redo(expected_revision=before.revision)
        assert replay.data == saved.data and not replay.is_dirty
        restored = session.undo(expected_revision=replay.revision)
        initial = session.undo(expected_revision=restored.revision)
        assert initial.data == document() and initial.undo_depth == 0


@pytest.mark.parametrize("command", ["empty_apply", "equal_apply"])
def test_noop_reply_allocation_failure_preserves_saved_marker_and_future(monkeypatch, command):
    session, before, saved = branched_session()
    operation = command_call(session, before, command)

    def fail_reply(*args, **kwargs):
        raise MemoryError("synthetic reply allocation failure")

    with monkeypatch.context() as patch:
        patch.setattr(SessionSnapshot, "__init__", fail_reply)
        with pytest.raises(MemoryError, match="synthetic reply"):
            operation()
    assert session.snapshot() == before
    replay = session.redo(expected_revision=before.revision)
    assert replay.data == saved.data and not replay.is_dirty


def test_mutating_caller_limits_cannot_relax_original_package_budget():
    data = document()
    package_limits = DocxLimits(max_archive_bytes=len(data))
    session = DocxSession(data, limits=package_limits)
    before = session.snapshot()
    object.__setattr__(package_limits, "max_archive_bytes", len(data) * 100)
    with pytest.raises(DocxError) as caught:
        apply_text(session, "longer content")
    assert caught.value.code == "package_limit_exceeded"
    assert session.snapshot() == before


@pytest.mark.parametrize(
    "limits_type,keyword,error_type",
    [
        (DocxLimits, "limits", DocxError),
        (ProjectionLimits, "projection_limits", ProjectionError),
        (SessionLimits, "session_limits", SessionError),
    ],
)
def test_limit_subclasses_cannot_supply_custom_validation(limits_type, keyword, error_type):
    class CustomLimits(limits_type):
        def __post_init__(self):
            pass

    limits = CustomLimits()
    with pytest.raises(error_type) as caught:
        DocxSession(document(), **{keyword: limits})
    assert caught.value.code == "invalid_input"


@pytest.mark.parametrize("command", ["apply", "undo", "redo", "mark_saved"])
@pytest.mark.parametrize(
    "invalid_revision", [True, False, -1, 3.0, "3", None, type("Number", (int,), {})(3)]
)
def test_every_command_rejects_noncanonical_revisions_without_changing_history(
    command, invalid_revision
):
    session, before, saved = branched_session()
    args = (None,) if command == "apply" else ()
    with pytest.raises(SessionError) as caught:
        getattr(session, command)(*args, expected_revision=invalid_revision)
    assert caught.value.code == "invalid_input"
    assert session.snapshot() == before
    replay = session.redo(expected_revision=before.revision)
    assert replay.data == saved.data and not replay.is_dirty


@pytest.mark.parametrize("field", fields(SessionLimits))
def test_caller_history_limit_cannot_relax_after_session_open(field):
    data = document()
    limits = SessionLimits(
        max_history_states=1 if field.name == "max_history_states" else 100,
        max_history_bytes=len(data) if field.name == "max_history_bytes" else 134217728,
    )
    session = DocxSession(data, session_limits=limits)
    object.__setattr__(limits, field.name, 134217728)
    if field.name == "max_history_bytes":
        before = session.snapshot()
        with pytest.raises(SessionError) as caught:
            apply_text(session, "a larger version")
        assert caught.value.code == "session_limit_exceeded"
        assert session.snapshot() == before
    else:
        changed = apply_text(session, "a larger version")
        assert changed.undo_depth == 0
        with pytest.raises(SessionError) as caught:
            session.undo(expected_revision=changed.revision)
        assert caught.value.code == "nothing_to_undo"


@pytest.mark.parametrize("states,byte_positions", [(1, 1), (2, 3), (5, 2), (4, 4)])
def test_mixed_commands_follow_exact_byte_history_model(states, byte_positions):
    data = document()
    byte_budget = len(data) * byte_positions + 40
    session = DocxSession(
        data,
        session_limits=SessionLimits(max_history_states=states, max_history_bytes=byte_budget),
    )
    undo, redo = [], []
    revision, saved = 0, data
    generator = random.Random(states * 100 + byte_positions)
    commands = ["edit", "noop", "undo", "redo", "save", "stale", "mismatch", "mutate"]
    # Ensure over-budget edits occur along with long and short repeated content.
    texts = ["alpha", "beta", "gamma", "A😀e\u0301Ж", "x" * 90, "z" * (byte_budget + 1)]

    for step in range(100):
        command = commands[step % len(commands)] if step < 8 else generator.choice(commands)
        before = session.snapshot()
        if command == "edit":
            edit = request(data, generator.choice(texts))
            candidate = export_docx_ranges(data, (edit,))
            if len(candidate) > byte_budget:
                with pytest.raises(SessionError) as caught:
                    session.apply((edit,), expected_revision=revision)
                assert caught.value.code == "session_limit_exceeded"
                assert session.snapshot() == before
            else:
                session.apply((edit,), expected_revision=revision)
                if candidate != data:
                    undo.append(data)
                    data, redo, revision = candidate, [], revision + 1
                    while len(undo) + 1 > states or sum(map(len, undo)) + len(data) > byte_budget:
                        undo.pop(0)
        elif command in ("undo", "redo"):
            history = undo if command == "undo" else redo
            destination = redo if command == "undo" else undo
            if not history:
                with pytest.raises(SessionError) as caught:
                    getattr(session, command)(expected_revision=revision)
                assert caught.value.code == "nothing_to_" + command
                assert session.snapshot() == before
            else:
                getattr(session, command)(expected_revision=revision)
                destination.append(data)
                data = history.pop()
                revision += 1
        elif command == "save":
            session.mark_saved(expected_revision=revision)
            saved = data
        elif command == "noop":
            edits = () if step % 2 else (request(data, before.projection.blocks[0].text),)
            assert session.apply(edits, expected_revision=revision) == before
        elif command == "stale":
            operation = generator.choice(("apply", "undo", "redo", "mark_saved"))
            args = (None,) if operation == "apply" else ()
            with pytest.raises(SessionError) as caught:
                getattr(session, operation)(*args, expected_revision=revision + 1)
            assert caught.value.code == "stale_revision"
            assert session.snapshot() == before
        elif command == "mismatch":
            with pytest.raises(RangeError) as caught:
                session.apply(
                    (request(data, "branch", expected="wrong"),), expected_revision=revision
                )
            assert caught.value.code == "text_mismatch"
            assert session.snapshot() == before
        else:
            object.__setattr__(before.projection.source.entries[0], "size_bytes", -1)
            object.__setattr__(before.projection.source.relationships[0], "target", "poison")
            object.__setattr__(before.projection.body_anchor, "path", (999,))
            object.__delattr__(before.projection.blocks[0].spans[0], "text")
            object.__setattr__(before, "is_dirty", not before.is_dirty)
            object.__setattr__(before, "undo_depth", 999)

        actual = session.snapshot()
        assert actual.data == data
        assert actual.projection == project_docx(data)
        assert actual.revision == revision
        assert actual.is_dirty is (data != saved)
        assert actual.undo_depth == len(undo) and actual.redo_depth == len(redo)
        assert len(undo) + 1 + len(redo) <= states
        assert sum(map(len, undo + [data] + redo)) <= byte_budget
