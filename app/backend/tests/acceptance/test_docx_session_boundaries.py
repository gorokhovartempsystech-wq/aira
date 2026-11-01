"""Independent state-machine, budget and isolation boundaries for D02-05."""

import base64
import json
import random
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest
from docx_projection_fixtures import package, paragraph

ROOT = Path(__file__).resolve().parents[2]


def api():
    return import_module("ara.docx_package.session")


def source(text="alpha"):
    return package(paragraph(text))[0]


def edit(data, replacement, expected=None):
    projection = import_module("ara.docx_package.projection").project_docx(data)
    span = projection.blocks[0].spans[0]
    ranges = import_module("ara.docx_package.ranges")
    return ranges.RangeEdit(
        ranges.TextPosition(span.anchor, 0),
        ranges.TextPosition(span.anchor, len(span.text)),
        span.text if expected is None else expected,
        replacement,
    )


def apply(session, text):
    before = session.snapshot()
    return session.apply((edit(before.data, text),), expected_revision=before.revision)


def assert_error(surface, code, operation):
    with pytest.raises(surface.SessionError) as caught:
        operation()
    assert caught.value.code == code
    assert str(caught.value) == caught.value.message
    assert caught.value.message
    assert "alpha" not in str(caught.value)


@pytest.mark.parametrize("revision", [True, False, -1, 0.0, "0", None])
def test_invalid_revision_does_not_change_any_state(revision):
    module = api()
    session = module.DocxSession(source())
    before = session.snapshot()
    assert_error(module, "invalid_input", lambda: session.apply((), expected_revision=revision))
    assert session.snapshot() == before


@pytest.mark.parametrize("command", ["apply", "undo", "redo", "mark_saved"])
def test_stale_commands_rejected_after_aba_even_when_source_bytes_match(command):
    module = api()
    session = module.DocxSession(source())
    initial = session.snapshot()
    apply(session, "beta")
    before = session.undo(expected_revision=1)
    assert before.data == initial.data and before.revision == 2
    args = ((),) if command == "apply" else ()
    assert_error(
        module, "stale_revision", lambda: getattr(session, command)(*args, expected_revision=0)
    )
    assert session.snapshot() == before
    assert session.redo(expected_revision=2).projection.blocks[0].text == "beta"


def test_stale_revision_is_checked_before_bad_edit_payload():
    module = api()
    session = module.DocxSession(source())
    apply(session, "beta")
    before = session.snapshot()
    assert_error(module, "stale_revision", lambda: session.apply(None, expected_revision=0))
    assert session.snapshot() == before


@pytest.mark.parametrize("command,code", [("undo", "nothing_to_undo"), ("redo", "nothing_to_redo")])
def test_empty_history_has_safe_error_without_mutation(command, code):
    module = api()
    session = module.DocxSession(source())
    before = session.snapshot()
    assert_error(module, code, lambda: getattr(session, command)(expected_revision=0))
    assert session.snapshot() == before


@pytest.mark.parametrize("field", ["max_history_states", "max_history_bytes"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_history_limits_are_strict_positive_integers(field, value):
    module = api()
    assert_error(module, "invalid_input", lambda: module.SessionLimits(**{field: value}))


@pytest.mark.parametrize("damage", ["zero", "deleted"])
def test_mutated_session_limits_are_rechecked_on_open(damage):
    module = api()
    limits = module.SessionLimits()
    if damage == "zero":
        object.__setattr__(limits, "max_history_states", 0)
    else:
        object.__delattr__(limits, "max_history_states")
    assert_error(
        module, "invalid_input", lambda: module.DocxSession(source(), session_limits=limits)
    )


@pytest.mark.parametrize("kind", ["docx", "projection"])
def test_lower_limits_are_rechecked_and_keep_lower_error_class(kind):
    module = api()
    lower = import_module("ara.docx_package" + (".projection" if kind == "projection" else ""))
    cls = lower.DocxLimits if kind == "docx" else lower.ProjectionLimits
    error = lower.DocxError if kind == "docx" else lower.ProjectionError
    name = "max_archive_bytes" if kind == "docx" else "max_nodes"
    keyword = "limits" if kind == "docx" else "projection_limits"
    limits = cls()
    object.__delattr__(limits, name)
    with pytest.raises(error) as caught:
        module.DocxSession(source(), **{keyword: limits})
    assert caught.value.code == "invalid_input"
    with pytest.raises(error) as caught:
        module.DocxSession(source(), **{keyword: {}})
    assert caught.value.code == "invalid_input"


def test_caller_owned_limits_are_copied_and_cannot_poison_existing_session():
    module = api()
    docx = import_module("ara.docx_package").DocxLimits()
    projection = import_module("ara.docx_package.projection").ProjectionLimits()
    history = module.SessionLimits(max_history_states=3)
    session = module.DocxSession(
        source(), limits=docx, projection_limits=projection, session_limits=history
    )
    object.__setattr__(docx, "max_archive_bytes", 1)
    object.__setattr__(projection, "max_nodes", 1)
    object.__setattr__(history, "max_history_states", 1)
    one = apply(session, "beta")
    two = apply(session, "gamma")
    assert one.undo_depth == 1 and two.undo_depth == 2
    assert session.undo(expected_revision=2).data == one.data


def test_mutating_returned_snapshot_nested_dtos_cannot_poison_session_or_history():
    module = api()
    raw = source()
    session = module.DocxSession(raw)
    initial = session.snapshot()
    changed = apply(session, "beta")
    saved_bytes = changed.data
    session.mark_saved(expected_revision=1)
    object.__setattr__(initial, "data", b"wrong")
    object.__setattr__(initial.projection.source, "_original", b"wrong")
    object.__setattr__(initial.projection.blocks[0], "text", "wrong")
    object.__setattr__(changed.projection.blocks[0].spans[0].anchor, "source_sha256", "0" * 64)
    object.__setattr__(changed.projection.source, "sha256", "0" * 64)
    object.__setattr__(changed, "revision", 999)
    current = session.snapshot()
    assert current.data == saved_bytes and current.revision == 1 and not current.is_dirty
    assert current.projection.source.sha256 != "0" * 64
    restored = session.undo(expected_revision=1)
    assert restored.data == raw and restored.projection.blocks[0].text == "alpha"
    replayed = session.redo(expected_revision=2)
    assert replayed.data == saved_bytes and replayed.is_dirty is False


@pytest.mark.parametrize("command", ["apply", "undo", "redo", "mark_saved"])
def test_failure_building_reply_does_not_commit_any_part_of_a_command(monkeypatch, command):
    module = api()
    session = module.DocxSession(source())
    apply(session, "beta")
    apply(session, "gamma")
    session.mark_saved(expected_revision=2)
    before = session.undo(expected_revision=2)
    # Every command now has a meaningful state change available, including save.
    assert before.undo_depth == before.redo_depth == 1 and before.is_dirty
    kwargs = {"expected_revision": before.revision}
    args = ((edit(before.data, "delta"),),) if command == "apply" else ()
    snapshot_class = module.SessionSnapshot

    def failing_snapshot(*args, **kwargs):
        raise RuntimeError("Synthetic reply allocation failure")

    # Fail preparation of the public DTO, including replace/copy construction paths.
    with monkeypatch.context() as patch:
        patch.setattr(snapshot_class, "__init__", failing_snapshot)
        patch.setattr(snapshot_class, "__copy__", failing_snapshot, raising=False)
        patch.setattr(snapshot_class, "__deepcopy__", failing_snapshot, raising=False)
        with pytest.raises(RuntimeError, match="Synthetic reply allocation failure"):
            getattr(session, command)(*args, **kwargs)
    assert session.snapshot() == before
    restored = session.redo(expected_revision=before.revision)
    assert restored.projection.blocks[0].text == "gamma" and not restored.is_dirty


def test_state_budget_evicts_oldest_undo_but_retains_last_edit():
    module = api()
    session = module.DocxSession(
        source(), session_limits=module.SessionLimits(max_history_states=2)
    )
    one = apply(session, "beta")
    two = apply(session, "gamma")
    assert two.undo_depth == 1 and two.redo_depth == 0
    before = session.undo(expected_revision=2)
    assert before.data == one.data and before.undo_depth == 0 and before.redo_depth == 1
    assert_error(module, "nothing_to_undo", lambda: session.undo(expected_revision=3))
    assert session.snapshot() == before
    assert session.redo(expected_revision=3).data == two.data


def test_one_state_budget_preserves_dirty_marker_after_saved_state_is_evicted():
    module = api()
    session = module.DocxSession(
        source(), session_limits=module.SessionLimits(max_history_states=1)
    )
    saved = apply(session, "beta")
    session.mark_saved(expected_revision=1)
    changed = apply(session, "gamma")
    assert changed.is_dirty and changed.undo_depth == changed.redo_depth == 0
    restored = apply(session, "beta")
    assert restored.data == saved.data
    assert restored.is_dirty is False and restored.undo_depth == 0


def test_branch_clears_redo_before_applying_history_budget():
    module = api()
    session = module.DocxSession(
        source(), session_limits=module.SessionLimits(max_history_states=2)
    )
    apply(session, "beta")
    before = session.undo(expected_revision=1)
    branch = apply(session, "gamma")
    assert branch.undo_depth == 1 and branch.redo_depth == 0
    assert session.undo(expected_revision=3).data == before.data


def test_repeated_byte_content_counts_once_per_history_position():
    module = api()
    ranges = import_module("ara.docx_package.ranges")
    raw = source()
    b = ranges.export_docx_ranges(raw, (edit(raw, "beta"),))
    c = ranges.export_docx_ranges(b, (edit(b, "gamma"),))
    assert ranges.export_docx_ranges(c, (edit(c, "beta"),)) == b
    budget = len(b) + len(c)
    session = module.DocxSession(b, session_limits=module.SessionLimits(max_history_bytes=budget))
    apply(session, "gamma")
    final = apply(session, "beta")
    assert final.data == b and final.undo_depth == 1
    previous = session.undo(expected_revision=2)
    assert previous.data == c and previous.undo_depth == 0


def test_byte_budget_is_inclusive_and_evicts_only_oldest_states():
    module = api()
    ranges = import_module("ara.docx_package.ranges")
    a = source()
    b = ranges.export_docx_ranges(a, (edit(a, "beta"),))
    c = ranges.export_docx_ranges(b, (edit(b, "gamma"),))
    budget = max(len(a) + len(b), len(b) + len(c))
    assert len(a) + len(b) + len(c) > budget
    session = module.DocxSession(a, session_limits=module.SessionLimits(max_history_bytes=budget))
    assert apply(session, "beta").undo_depth == 1
    assert apply(session, "gamma").undo_depth == 1
    restored = session.undo(expected_revision=2)
    assert restored.data == b and restored.undo_depth == 0 and restored.redo_depth == 1
    assert session.redo(expected_revision=3).data == c


def test_current_file_must_fit_byte_budget_at_open():
    module = api()
    raw = source()
    exact = module.DocxSession(raw, session_limits=module.SessionLimits(max_history_bytes=len(raw)))
    assert exact.snapshot().data == raw
    assert_error(
        module,
        "session_limit_exceeded",
        lambda: module.DocxSession(
            raw, session_limits=module.SessionLimits(max_history_bytes=len(raw) - 1)
        ),
    )


def test_too_large_new_current_fails_atomically_and_keeps_redo():
    module = api()
    raw = source()
    session = module.DocxSession(
        raw, session_limits=module.SessionLimits(max_history_bytes=len(raw) * 3)
    )
    saved = apply(session, "beta")
    before = session.undo(expected_revision=1)
    randomizer = random.Random(42)
    text = "".join(randomizer.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=30000))
    assert_error(module, "session_limit_exceeded", lambda: apply(session, text))
    assert session.snapshot() == before
    assert session.redo(expected_revision=2).data == saved.data


def test_lower_error_preserves_redo_and_current_snapshot():
    module = api()
    ranges = import_module("ara.docx_package.ranges")
    session = module.DocxSession(source())
    applied = apply(session, "beta")
    before = session.undo(expected_revision=1)
    with pytest.raises(ranges.RangeError) as caught:
        session.apply((edit(before.data, "gamma", expected="wrong"),), expected_revision=2)
    assert caught.value.code == "text_mismatch"
    assert session.snapshot() == before
    with pytest.raises(ranges.RangeError) as caught:
        session.apply((edit(applied.data, "gamma"),), expected_revision=2)
    assert caught.value.code == "stale_source"
    assert session.snapshot() == before
    assert session.redo(expected_revision=2).data == applied.data


def test_range_budget_and_projection_budget_are_not_bypassed():
    module = api()
    ranges = import_module("ara.docx_package.ranges")
    projection = import_module("ara.docx_package.projection")
    raw = source()
    with pytest.raises(projection.ProjectionError) as caught:
        module.DocxSession(raw, projection_limits=projection.ProjectionLimits(max_nodes=1))
    assert caught.value.code == "projection_limit_exceeded"
    session = module.DocxSession(raw)
    before = session.snapshot()
    with pytest.raises(ranges.RangeError) as caught:
        session.apply(
            (edit(raw, "long replacement"),),
            expected_revision=0,
            range_limits=ranges.RangeLimits(max_total_replacement_chars=1),
        )
    assert caught.value.code == "range_limit_exceeded"
    assert session.snapshot() == before


def test_apply_preserves_constructor_package_limits_for_the_exported_content():
    module = api()
    package_api = import_module("ara.docx_package")
    raw = source()
    largest_part = max(entry.size_bytes for entry in package_api.open_docx(raw).entries)
    limits = package_api.DocxLimits(max_part_bytes=largest_part)
    session = module.DocxSession(raw, limits=limits)
    before = session.snapshot()
    with pytest.raises(package_api.DocxError) as caught:
        apply(session, "x" * (largest_part + 1000))
    assert caught.value.code == "package_limit_exceeded"
    assert session.snapshot() == before


def test_readable_protected_package_opens_but_session_cannot_edit_it():
    module = api()
    editing = import_module("ara.docx_package.editing")
    raw, _ = package(
        paragraph("alpha"),
        extra_parts={
            "custom/settings.xml": (
                b'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b"<w:documentProtection/></w:settings>"
            )
        },
        extra_types={
            "custom/settings.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
            )
        },
    )
    session = module.DocxSession(raw)
    before = session.snapshot()
    assert session.apply((), expected_revision=0) == before
    with pytest.raises(editing.EditError):
        apply(session, "beta")
    assert session.snapshot() == before


def test_import_and_commands_have_no_external_io_or_logging():
    api()
    code = """
import base64, builtins, importlib, io, json, logging, os, socket, subprocess, tempfile
from pathlib import Path
import urllib.request, zipfile, dataclasses, hashlib, copy, re, struct, codecs
from xml.etree import ElementTree
import xml.parsers.expat
import psycopg, sqlalchemy
import ara.config, ara.db
import ara.docx_package.ranges as ranges
raw = base64.b64decode(PAYLOAD)
names = ['ara.docx_package.session'] + [
    '.'.join(p.with_suffix('').parts[1:])
    for p in sorted(Path('src/ara/docx_package/session').rglob('*.py'))
    if p.name != '__init__.py'
]
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external I/O in DOCX session')
for target, name in (
    (builtins, 'open'), (io, 'open'), (Path, 'open'), (Path, 'read_text'), (Path, 'read_bytes'),
    (Path, 'write_text'), (Path, 'write_bytes'), (Path, 'mkdir'), (os, 'open'), (os, 'mkdir'),
    (os, 'system'), (os, 'popen'), (socket, 'socket'), (socket, 'create_connection'),
    (subprocess, 'Popen'), (subprocess, 'run'), (urllib.request, 'urlopen'),
    (tempfile, 'TemporaryFile'), (tempfile, 'NamedTemporaryFile'), (tempfile, 'mkdtemp'),
    (psycopg, 'connect'), (sqlalchemy, 'create_engine'), (ara.config, 'load_settings'),
    (ara.db, 'create_database_engine'), (logging.Logger, '_log'),
):
    setattr(target, name, forbidden)
for name in names:
    importlib.import_module(name)
module = importlib.import_module('ara.docx_package.session')
session = module.DocxSession(raw)
span = session.snapshot().projection.blocks[0].spans[0]
change = ranges.RangeEdit(ranges.TextPosition(span.anchor, 0),
    ranges.TextPosition(span.anchor, len(span.text)), span.text, 'beta')
changed = session.apply((change,), expected_revision=0)
assert session.undo(expected_revision=1).data == raw
assert session.redo(expected_revision=2).data == changed.data
assert session.mark_saved(expected_revision=3).is_dirty is False
assert session.apply((), expected_revision=3).revision == 3
""".replace("PAYLOAD", json.dumps(base64.b64encode(source()).decode()))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""
