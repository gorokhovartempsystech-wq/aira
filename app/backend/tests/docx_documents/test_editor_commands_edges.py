"""Command identity, memory publication cuts and strict payload boundaries."""

import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from ara.docx_documents._dto import MAX_REVISION
from ara.docx_package.editor import Caret, EditorSelection, EditorSession
from ara.docx_package.session import SessionLimits
from ara.docx_package.structure import DeleteParagraph
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_checkpoints import reject
from tests.acceptance.test_docx_editor_commands import command, opened
from tests.acceptance.test_docx_editor_registry import api


def test_same_request_concurrency_and_canonical_proof(run_world):
    _, _, registry, view = opened(run_world)
    request = command(registry, view, "insert_text", "New 🧪")
    barrier = Barrier(2)

    def call():
        barrier.wait(5)
        return registry.command(**request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(call), pool.submit(call)
        first, second = a.result(10), b.result(10)
    assert first == second and first.command_sequence == 1
    payload = dict(
        version=1,
        registry_id=str(view.registry_id),
        document_id=str(view.document_id),
        session_id=str(view.session_id),
        command_id=str(request["command_id"]),
        expected_command_sequence="0",
        expected_session_revision="0",
        action="insert_text",
        value="New 🧪",
        after=None,
    )
    expected = sha256(
        b"ara.docx.editor-command.v1\0"
        + json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert first.last_command.request_sha256 == expected


@pytest.mark.parametrize("after_commit", [False, True])
def test_read_commit_failure_after_candidate_does_not_publish(run_world, monkeypatch, after_commit):
    runtime, _, registry, view = opened(run_world)
    request = command(registry, view, "paste_text", "One\nTwo")
    real = runtime.engine.dialect.do_commit

    def fail(conn):
        if after_commit:
            real(conn)
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(lambda: registry.command(**request), "storage_unavailable", 503)
    assert registry.snapshot(document_id=view.document_id, session_id=view.session_id) == view
    assert set(registry._budget.groups) == {view.session_id}
    assert registry.command(**request).command_sequence == 1


def test_dto_failure_does_not_apply_typing_twice(run_world, monkeypatch):
    _, _, registry, view = opened(run_world)
    request = command(registry, view, "insert_text", "Once ")
    model = importlib.import_module("ara.docx_editor._models")

    def fail(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(model.EditorView, "__post_init__", fail)
        reject(lambda: registry.command(**request), "editor_error", 500)
    assert registry.snapshot(document_id=view.document_id, session_id=view.session_id) == view
    result = registry.command(**request)
    assert result.editor.document.projection.blocks[0].text.startswith("Once Device")
    assert registry.command(**request) == result


def test_union_budget_rejects_candidate_even_when_its_final_history_fits(run_world):
    _, _, registry, view = opened(run_world)
    actor = registry._actors[(view.document_id, view.session_id)]
    # A smaller trusted per-core history exercises dropping a position during this edit.
    core = EditorSession(
        view.editor.document.data, session_limits=SessionLimits(max_history_states=1)
    )
    actor.state = replace(actor.state, editor=core)
    registry._budget.maximum = len(view.editor.document.data) + 100
    request = command(registry, view, "insert_text", "New ")
    candidate = EditorSession(
        view.editor.document.data, session_limits=SessionLimits(max_history_states=1)
    )
    after = candidate.insert_text("New ", expected_revision=0)
    assert len(after.document.data) < registry._budget.maximum
    reject(lambda: registry.command(**request), "editor_limit_exceeded", 413)
    assert registry.snapshot(document_id=view.document_id, session_id=view.session_id) == view
    assert set(registry._budget.groups) == {view.session_id}
    registry._budget.maximum = 268435456
    assert registry.command(**request).command_sequence == 1


def test_sequence_exhaustion_and_core_exhaustion_are_independent(run_world):
    _, _, registry, view = opened(run_world)
    actor = registry._actors[(view.document_id, view.session_id)]
    actor.state = replace(actor.state, command_sequence=MAX_REVISION)
    reject(
        lambda: registry.command(
            **command(registry, replace(view, command_sequence=MAX_REVISION), "insert_text", "")
        ),
        "revision_exhausted",
    )
    actor.state = replace(actor.state, command_sequence=0)
    core = actor.state.editor._state.core
    core._state = replace(core._state, revision=MAX_REVISION)
    maxview = registry.snapshot(document_id=view.document_id, session_id=view.session_id)
    reject(
        lambda: registry.command(**command(registry, maxview, "insert_text", "")),
        "revision_exhausted",
    )
    captured = registry.command(**command(registry, maxview, "capture", maxview.editor.selection))
    assert captured.command_sequence == 1 and captured.editor.document.revision == MAX_REVISION


def test_delete_structure_and_noncollapsed_error_preserve_original_editor(run_world):
    _, _, registry, view = opened(run_world)
    pasted = registry.command(**command(registry, view, "paste_text", "One\nTwo"))
    p = pasted.editor.document.projection.blocks[0]
    target = importlib.import_module("ara.docx_package.editor").CaretTarget(0, 0)
    after = importlib.import_module("ara.docx_package.editor").SelectionTarget(target, target)
    deleted = registry.command(
        **command(registry, pasted, "structure", (DeleteParagraph(p.anchor, p.text),), after)
    )
    p = deleted.editor.document.projection.blocks[0]
    selection = EditorSelection(Caret(p.anchor, 0), Caret(p.anchor, 1))
    selected = registry.command(**command(registry, deleted, "capture", selection))
    reject(
        lambda: registry.command(**command(registry, selected, "insert_text", "X")),
        "unsupported_intent",
        422,
    )
    assert registry.snapshot(document_id=view.document_id, session_id=view.session_id) == selected
    assert view.editor.document.undo_depth == 0 and not view.editor.document.is_dirty


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_command_sequence", True),
        ("expected_session_revision", -1),
        ("command_id", "invalid"),
        ("expected_command_sequence", 2**63),
    ],
)
def test_bad_identity_has_no_effect(run_world, field, value):
    _, _, registry, view = opened(run_world)
    request = command(registry, view, "insert_text", "X")
    reject(lambda: registry.command(**{**request, field: value}), "validation_error", 422)
    assert registry.snapshot(document_id=view.document_id, session_id=view.session_id) == view


def test_payload_shape_is_checked_before_hash_and_deepcopy(run_world):
    _, _, registry, view = opened(run_world)
    base = api().EditorCommand("capture", view.editor.selection)
    for field, value in [("value", object()), ("after", object()), ("action", "unknown")]:
        damaged = deepcopy(base)
        object.__setattr__(damaged, field, value)
        request = command(registry, view, "insert_text", "X")
        reject(lambda: registry.command(**{**request, "command": damaged}), "validation_error", 422)
    damaged = deepcopy(base)
    object.__setattr__(damaged.value.anchor.anchor, "path", tuple(range(129)))
    request = command(registry, view, "insert_text", "X")
    reject(lambda: registry.command(**{**request, "command": damaged}), "validation_error", 422)
    assert registry.snapshot(document_id=view.document_id, session_id=view.session_id) == view


def test_codepoint_paste_and_long_nonbmp_fingerprint_are_bounded(run_world):
    _, _, registry, view = opened(run_world)
    result = registry.command(**command(registry, view, "paste_text", "🧪" * 128))
    assert result.editor.selection.focus.offset == 128
    large = api().EditorCommand("paste_text", "🧪" * 1000000)
    from ara.docx_editor._commands import fingerprint

    digest = fingerprint(view.registry_id, view.document_id, view.session_id, uuid4(), 0, 0, large)
    assert len(digest) == 64
