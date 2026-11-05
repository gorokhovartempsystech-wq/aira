"""E4C1 explicit effective visibility commands preserve durable user intent."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from test_docx_review_preferences import counts, reject
from test_docx_review_remapping import TEXTS
from test_docx_review_resolution import analyze, get, hide, state, two_origins
from test_docx_review_resolution import resolution_world as resolution_world

from ara import docx_documents as documents
from ara import docx_review_preferences as preferences
from ara.documents.storage import DocumentError
from ara.docx_review_resolution import ResolutionLimits


def api():
    return importlib.import_module("ara.docx_review_commands")


@pytest.fixture
def command_world(resolution_world):
    api()
    return resolution_world


def visibility(w, target=None, *, hidden=True, **changes):
    target = target or w["first"]
    return (
        dict(
            document_id=w["doc"],
            command_id=uuid4(),
            expected_revision=state(w).revision,
            hidden=hidden,
            **target,
        )
        | changes
    )


def clearing(w, **changes):
    return (
        dict(document_id=w["doc"], command_id=uuid4(), expected_revision=state(w).revision)
        | changes
    )


def test_initial_clear_is_confirmed_noop_with_default_preferences(command_world):
    w = command_world
    command = clearing(w)
    receipt = api().clear_hidden(w["runtime"], **command)
    assert receipt.kind == "unhide" and receipt.changed is False and receipt.revision == 1
    assert api().clear_hidden(w["runtime"], **command) == receipt
    assert state(w).show_questions and not state(w).show_hidden and counts(w) == (1, 0, 1)


def test_effective_hide_does_not_duplicate_the_existing_old_origin(command_world):
    w = command_world
    hide(w, w["first"])
    target = analyze(w, ("Distant insertion",) + TEXTS, at=3)
    before = state(w).hidden_keys
    receipt = api().set_hidden(w["runtime"], **visibility(w, target))
    assert receipt.changed is False and receipt.revision == 2
    assert state(w).hidden_keys == before and counts(w) == (1, 1, 2)
    assert get(w, target).hidden_keys and get(w, target).aliases[0].origin_keys == before


def test_unhide_removes_all_origins_that_resolve_to_current_finding(command_world):
    w = command_world
    _, target = two_origins(w)
    receipt = api().set_hidden(w["runtime"], **visibility(w, target, hidden=False))
    assert receipt.changed is True and receipt.revision == 3
    assert (
        get(w, target).hidden_keys == () and state(w).hidden_keys == () and counts(w) == (1, 0, 3)
    )
    noop = api().set_hidden(w["runtime"], **visibility(w, target, hidden=False))
    assert noop.changed is False and noop.revision == 4


def test_unrelated_changed_evidence_hides_are_not_deleted(command_world):
    w = command_world
    hide(w, w["first"])
    old = state(w).hidden_keys
    target = analyze(w, TEXTS[:2] + (TEXTS[2] + " changed",) + TEXTS[3:])
    receipt = api().set_hidden(w["runtime"], **visibility(w, target))
    assert receipt.changed is True and counts(w) == (1, 2, 2)
    receipt = api().set_hidden(w["runtime"], **visibility(w, target, hidden=False))
    assert receipt.changed is True and state(w).hidden_keys == old
    assert get(w, target).hidden_keys == () and counts(w) == (1, 1, 3)


def test_clear_preserves_filters_documents_results_and_command_history(command_world):
    w = command_world
    _, target = two_origins(w)
    preferences.set_preferences(
        w["runtime"],
        document_id=w["doc"],
        command_id=uuid4(),
        expected_revision=2,
        disabled_types=["formulation"],
        show_questions=False,
        show_hidden=True,
    )
    original = documents.get_docx(w["runtime"], document_id=w["doc"])
    with w["engine"].connect() as conn:
        results = conn.execute(
            text("SELECT run_id,result_data FROM docx_analysis_results ORDER BY run_id")
        ).all()
    receipt = api().clear_hidden(w["runtime"], **clearing(w))
    assert receipt.changed is True and receipt.revision == 4
    saved = state(w)
    assert (
        saved.disabled_types == ("formulation",) and not saved.show_questions and saved.show_hidden
    )
    assert saved.hidden_keys == () and get(w, target).hidden_keys == () and counts(w) == (1, 0, 4)
    assert documents.get_docx(w["runtime"], document_id=w["doc"]) == original
    with w["engine"].connect() as conn:
        assert (
            conn.execute(
                text("SELECT run_id,result_data FROM docx_analysis_results ORDER BY run_id")
            ).all()
            == results
        )


def test_clear_recovers_from_resolution_limit_without_decoding_origins(command_world, monkeypatch):
    w = command_world
    _, target = two_origins(w)
    reject(
        "preferences_resolution_limit",
        lambda: get(w, target, limits=ResolutionLimits(max_origins=1)),
    )
    module = importlib.import_module("ara.docx_review_resolution._resolve")

    def forbidden(*args, **kwargs):
        raise AssertionError("Clear must not decode origins")

    with monkeypatch.context() as patch:
        patch.setattr(module, "match_findings", forbidden)
        patch.setattr(module, "finding_keys", forbidden)
        receipt = api().clear_hidden(w["runtime"], **clearing(w))
    assert (
        receipt.changed and get(w, target, limits=ResolutionLimits(max_origins=1)).hidden_keys == ()
    )


def test_clear_keeps_working_with_corrupt_old_origin_bytes(command_world):
    w = command_world
    hide(w, w["first"])
    target = analyze(w, ("Changed intro",) + TEXTS[1:])
    with w["engine"].begin() as conn:
        conn.execute(
            text("UPDATE docx_analysis_results SET reply_data=:bad WHERE run_id=:run"),
            dict(bad=b"SYNTHETIC_PRIVATE", run=w["first"]["run_id"]),
        )
    reject("storage_error", lambda: get(w, target))
    receipt = api().clear_hidden(w["runtime"], **clearing(w))
    assert receipt.changed and get(w, target).hidden_keys == ()
    with w["engine"].connect() as conn:
        assert (
            bytes(
                conn.scalar(
                    text("SELECT reply_data FROM docx_analysis_results WHERE run_id=:run"),
                    dict(run=w["first"]["run_id"]),
                )
            )
            == b"SYNTHETIC_PRIVATE"
        )


def test_old_hide_and_clear_replays_never_reapply_state_or_require_decode(
    command_world, monkeypatch
):
    w = command_world
    command = visibility(w)
    first = api().set_hidden(w["runtime"], **command)
    clear = clearing(w)
    cleared = api().clear_hidden(w["runtime"], **clear)
    module = importlib.import_module("ara.docx_review_commands._commands")

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must precede resolution")

    monkeypatch.setattr(module, "resolve", forbidden)
    assert (
        api().set_hidden(w["runtime"], **command, limits=ResolutionLimits(max_record_bytes=1))
        == first
    )
    assert api().clear_hidden(w["runtime"], **clear) == cleared
    assert state(w).revision == 2 and counts(w) == (1, 0, 2)


@pytest.mark.parametrize("first_kind", ["clear", "old_hide", "old_preferences"])
def test_clear_and_v1_share_one_idempotency_namespace(command_world, first_kind):
    w = command_world
    identity = uuid4()
    clear = clearing(w, command_id=identity, expected_revision=0)
    legacy = visibility(w, command_id=identity, expected_revision=0)
    setting = dict(
        document_id=w["doc"],
        command_id=identity,
        expected_revision=0,
        disabled_types=[],
        show_questions=True,
        show_hidden=False,
    )
    if first_kind == "clear":
        api().clear_hidden(w["runtime"], **clear)
        reject("idempotency_conflict", lambda: preferences.set_hidden(w["runtime"], **legacy))
        reject("idempotency_conflict", lambda: preferences.set_preferences(w["runtime"], **setting))
        reject("idempotency_conflict", lambda: api().set_hidden(w["runtime"], **legacy))
    else:
        if first_kind == "old_hide":
            preferences.set_hidden(w["runtime"], **legacy)
        else:
            preferences.set_preferences(w["runtime"], **setting)
        reject("idempotency_conflict", lambda: api().clear_hidden(w["runtime"], **clear))
    assert state(w).revision == 1


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_effective_commands_commit_once_or_conflict(command_world, same_key):
    w = command_world
    barrier = Barrier(2)
    first = visibility(w)
    second = first if same_key else visibility(w)

    def apply(command):
        barrier.wait(3)
        try:
            return api().set_hidden(w["runtime"], **command)
        except DocumentError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(apply, [first, second]))
    if same_key:
        assert outcomes[0] == outcomes[1] and outcomes[0].revision == 1
    else:
        assert sum(value == "preferences_conflict" for value in outcomes) == 1
        assert sum(getattr(value, "revision", None) == 1 for value in outcomes) == 1
    assert counts(w) == (1, 1, 1)


@pytest.mark.parametrize("action", ["hide", "clear"])
@pytest.mark.parametrize("after", [False, True])
def test_unknown_commit_outcome_is_reconciled_by_original_receipt(
    command_world, monkeypatch, action, after
):
    w = command_world
    if action == "clear":
        hide(w, w["first"])
    original_revision = state(w).revision
    command = visibility(w) if action == "hide" else clearing(w)
    function = api().set_hidden if action == "hide" else api().clear_hidden
    marked = Event()
    original = w["engine"].dialect.do_commit

    def mark(conn, cursor, statement, parameters, context, executemany):
        if "insert into docx_review_receipts" in statement.lower():
            marked.set()

    def commit(connection):
        if marked.is_set():
            marked.clear()
            if after:
                original(connection)
            raise OperationalError("COMMIT", {}, RuntimeError("SYNTHETIC_PRIVATE"))
        return original(connection)

    event.listen(w["engine"], "before_cursor_execute", mark)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(w["engine"].dialect, "do_commit", commit)
            reject("storage_unavailable", lambda: function(w["runtime"], **command))
    finally:
        event.remove(w["engine"], "before_cursor_execute", mark)
    assert state(w).revision == original_revision + int(after)
    receipt = function(w["runtime"], **command)
    assert receipt.changed and receipt.revision == original_revision + 1
    assert counts(w) == (1, 1 if action == "hide" else 0, original_revision + 1)


@pytest.mark.parametrize("race", ["owner", "preferences", "origin"])
def test_scope_state_and_origin_are_rechecked_after_resolution(command_world, monkeypatch, race):
    w = command_world
    hide(w, w["first"])
    target = analyze(w, ("Changed far intro",) + TEXTS[1:])
    command = visibility(w, target, hidden=False)
    module = importlib.import_module("ara.docx_review_commands._commands")
    original = module.resolve

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if race == "preferences":
            preferences.set_preferences(
                w["runtime"],
                document_id=w["doc"],
                command_id=uuid4(),
                expected_revision=1,
                disabled_types=["formulation"],
                show_questions=True,
                show_hidden=False,
            )
        else:
            with w["engine"].begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout='500ms'"))
                if race == "owner":
                    conn.execute(
                        text("UPDATE projects SET owner_id=:owner WHERE id=:project"),
                        dict(
                            owner=w["world"]["runtimes"]["foreign"].user_id,
                            project=w["runtime"].project_id,
                        ),
                    )
                else:
                    conn.execute(
                        text("UPDATE docx_analysis_results SET reply_data=:bad WHERE run_id=:run"),
                        dict(bad=b"SYNTHETIC_PRIVATE", run=w["first"]["run_id"]),
                    )
        return result

    monkeypatch.setattr(module, "resolve", changed)
    expected = {
        "owner": "not_found",
        "preferences": "preferences_conflict",
        "origin": "storage_error",
    }[race]
    reject(expected, lambda: api().set_hidden(w["runtime"], **command))
    assert counts(w) == (1, 1, 2 if race == "preferences" else 1)


def test_prospective_hide_work_budget_never_commits_unreadable_state(command_world):
    import json

    w = command_world
    target = get(w).target
    size = len(json.loads(target.source.snapshot_data)["analysis_text"])
    command = visibility(w)
    reject(
        "preferences_resolution_limit",
        lambda: api().set_hidden(
            w["runtime"], **command, limits=ResolutionLimits(max_text_characters=3 * size - 1)
        ),
    )
    assert counts(w) == (0, 0, 0)
    receipt = api().set_hidden(
        w["runtime"], **command, limits=ResolutionLimits(max_text_characters=3 * size)
    )
    assert (
        receipt.changed
        and get(w, limits=ResolutionLimits(max_text_characters=3 * size)).hidden_keys
    )


@pytest.mark.parametrize("scope", ["peer", "foreign"])
def test_foreign_runtime_cannot_hide_or_clear(command_world, scope):
    w = command_world
    runtime = w["world"]["runtimes"][scope]
    reject("not_found", lambda: api().set_hidden(runtime, **visibility(w)))
    reject("not_found", lambda: api().clear_hidden(runtime, **clearing(w)))
    assert counts(w) == (0, 0, 0)


@pytest.mark.parametrize(
    "changes,code",
    [
        (dict(finding_id="df-" + "0" * 64), "not_found"),
        (dict(result_sha256="0" * 64), "preferences_conflict"),
        (dict(hidden=1), "validation_error"),
        (dict(expected_revision=True), "validation_error"),
    ],
)
def test_bad_visibility_request_never_mutates_state(command_world, changes, code):
    w = command_world
    reject(code, lambda: api().set_hidden(w["runtime"], **visibility(w, **changes)))
    assert counts(w) == (0, 0, 0)


def test_counter_exhaustion_refuses_new_clear_but_keeps_old_ack(command_world):
    w = command_world
    command = clearing(w)
    original = api().clear_hidden(w["runtime"], **command)
    with w["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_review_preferences SET revision=9223372036854775807"))
    reject("preferences_history_exhausted", lambda: api().clear_hidden(w["runtime"], **clearing(w)))
    assert api().clear_hidden(w["runtime"], **command) == original
    assert counts(w) == (1, 0, 1)


def test_hash_correct_clear_schema_tamper_is_not_a_valid_replay(command_world):
    import json
    from hashlib import sha256

    from test_docx_review_v1 import canonical

    w = command_world
    command = clearing(w)
    api().clear_hidden(w["runtime"], **command)
    with w["engine"].begin() as conn:
        raw = bytes(conn.scalar(text("SELECT command_data FROM docx_review_receipts")))
        parsed = json.loads(raw)
        assert (
            parsed["schema_version"] == "docx-review-clear/1"
            and parsed["operation"] == "clear_hidden"
        )
        parsed["operation"] = "different_action"
        bad = canonical(parsed)
        conn.execute(
            text("UPDATE docx_review_receipts SET command_data=:raw,command_sha256=:sha"),
            dict(raw=bad, sha=sha256(bad).hexdigest()),
        )
    reject("storage_error", lambda: api().clear_hidden(w["runtime"], **command))
    assert counts(w) == (1, 0, 1)


def test_explicit_clear_does_not_allow_reusing_an_old_unhide_key_to_hide(command_world):
    w = command_world
    hide(w, w["first"])
    command = visibility(w, hidden=False)
    original = api().set_hidden(w["runtime"], **command)
    api().clear_hidden(w["runtime"], **clearing(w))
    assert api().set_hidden(w["runtime"], **command) == original
    reject(
        "idempotency_conflict",
        lambda: api().set_hidden(w["runtime"], **(command | dict(hidden=True))),
    )
    assert state(w).hidden_keys == () and counts(w) == (1, 0, 3)


def test_concurrent_clear_and_effective_hide_have_one_cas_winner(command_world):
    w = command_world
    hide(w, w["first"])
    before = state(w).hidden_keys
    target = analyze(w, ("Distant prefix",) + TEXTS, at=3)
    clear, hidden = clearing(w), visibility(w, target)
    barrier = Barrier(2)

    def apply(pair):
        function, command = pair
        barrier.wait(3)
        try:
            return function(w["runtime"], **command)
        except DocumentError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(apply, [(api().clear_hidden, clear), (api().set_hidden, hidden)]))
    assert sum(value == "preferences_conflict" for value in results) == 1
    assert state(w).revision == 2
    if results[0] == "preferences_conflict":
        assert results[1].changed is False and state(w).hidden_keys == before
    else:
        assert results[0].changed is True and state(w).hidden_keys == ()
    assert counts(w)[2] == 2


@pytest.mark.parametrize("after", [False, True])
def test_multi_origin_unhide_is_atomic_across_commit_ack_loss(command_world, monkeypatch, after):
    w = command_world
    _, target = two_origins(w)
    command = visibility(w, target, hidden=False)
    marked = Event()
    original = w["engine"].dialect.do_commit

    def mark(conn, cursor, statement, parameters, context, executemany):
        if "insert into docx_review_receipts" in statement.lower():
            marked.set()

    def commit(connection):
        if marked.is_set():
            marked.clear()
            if after:
                original(connection)
            raise OperationalError("COMMIT", {}, RuntimeError("SYNTHETIC_PRIVATE"))
        return original(connection)

    event.listen(w["engine"], "before_cursor_execute", mark)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(w["engine"].dialect, "do_commit", commit)
            reject("storage_unavailable", lambda: api().set_hidden(w["runtime"], **command))
    finally:
        event.remove(w["engine"], "before_cursor_execute", mark)
    assert counts(w) == ((1, 0, 3) if after else (1, 2, 2))
    receipt = api().set_hidden(w["runtime"], **command)
    assert receipt.changed and receipt.revision == 3 and counts(w) == (1, 0, 3)
    assert get(w, target).hidden_keys == ()
