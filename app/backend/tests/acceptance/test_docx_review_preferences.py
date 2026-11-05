"""E2B durable presentation state with exact source validation and command receipts."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from test_docx_analysis_http import api_world as api_world
from test_docx_analysis_http import complete
from test_docx_analysis_storage_migrations import parents
from test_docx_editor_http import root
from test_docx_text_edit import seed

from ara.documents.runtime import DocumentRuntime
from ara.documents.storage import DocumentError

P, D, R = "docx_review_preferences", "docx_review_dismissals", "docx_review_receipts"


def api():
    return importlib.import_module("ara.docx_review_preferences")


@pytest.fixture
def prefs_world(api_world):
    api()
    world, item, app, http, s, p = api_world
    view, body, location, receipt = complete(api_world)
    result = http.get(root(item) + "/analysis-result").json()
    return dict(
        world=world,
        engine=world["engine"],
        runtime=world["runtimes"]["own"],
        item=item,
        doc=item.document_id,
        run=UUID(receipt["run_id"]),
        sha=result["stored_result_sha256"],
        finding=result["result"]["findings"][0]["finding_id"],
        http=http,
        platform=p,
        body=body,
        view=view,
        original=result,
    )


def state(w):
    return api().get_state(w["runtime"], document_id=w["doc"])


def command(w, *, hidden=True, **changes):
    return (
        dict(
            document_id=w["doc"],
            command_id=uuid4(),
            expected_revision=0,
            run_id=w["run"],
            result_sha256=w["sha"],
            finding_id=w["finding"],
            hidden=hidden,
        )
        | changes
    )


def prefs(w, **changes):
    return (
        dict(
            document_id=w["doc"],
            command_id=uuid4(),
            expected_revision=0,
            disabled_types=[],
            show_questions=True,
            show_hidden=False,
        )
        | changes
    )


def counts(w):
    with w["engine"].connect() as conn:
        return tuple(conn.scalar(text(f"SELECT count(*) FROM {table}")) for table in (P, D, R))


def reject(code, fn):
    with pytest.raises(DocumentError) as caught:
        fn()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
    return caught.value


def test_virtual_defaults_do_not_create_rows(prefs_world):
    w = prefs_world
    v = state(w)
    assert v.document_id == w["doc"] and v.revision == 0
    assert v.disabled_types == () and v.show_questions is True and v.show_hidden is False
    assert v.hidden_keys == () and counts(w) == (0, 0, 0)


def test_persist_hide_preferences_and_unhide_without_changing_analysis(prefs_world):
    w = prefs_world
    c = command(w)
    first = api().set_hidden(w["runtime"], **c)
    assert first.revision == 1 and first.expected_revision == 0 and first.changed is True
    hidden = state(w).hidden_keys
    assert len(hidden) == 1 and hidden[0].startswith("dh-")
    changed = api().set_preferences(
        w["runtime"],
        **prefs(
            w,
            expected_revision=1,
            disabled_types=["formulation"],
            show_questions=False,
            show_hidden=True,
        ),
    )
    assert changed.revision == 2 and changed.changed is True
    fresh_runtime = replace(w["runtime"])
    saved = api().get_state(fresh_runtime, document_id=w["doc"])
    assert saved.revision == 2 and saved.hidden_keys == hidden
    assert (
        saved.disabled_types == ("formulation",) and not saved.show_questions and saved.show_hidden
    )
    out = api().set_hidden(w["runtime"], **command(w, expected_revision=2, hidden=False))
    assert out.kind == "unhide" and out.changed is True and out.revision == 3
    assert state(w).hidden_keys == () and counts(w) == (1, 0, 3)
    assert w["http"].get(root(w["item"]) + "/analysis-result").json() == w["original"]
    assert w["platform"].launches == 1


def test_exact_old_replay_never_reverts_newer_state(prefs_world):
    w = prefs_world
    c = command(w)
    first = api().set_hidden(w["runtime"], **c)
    api().set_hidden(w["runtime"], **command(w, expected_revision=1, hidden=False))
    assert api().set_hidden(w["runtime"], **c) == first
    assert state(w).revision == 2 and state(w).hidden_keys == () and counts(w) == (1, 0, 2)
    reject(
        "idempotency_conflict", lambda: api().set_hidden(w["runtime"], **(c | {"hidden": False}))
    )


def test_new_noop_consumes_revision_and_pref_order_is_canonical(prefs_world):
    w = prefs_world
    one = api().set_preferences(w["runtime"], **prefs(w))
    assert one.revision == 1 and one.changed is False
    c = prefs(w, expected_revision=1, disabled_types=["formulation", "duplicate"])
    two = api().set_preferences(w["runtime"], **c)
    assert two.revision == 2 and state(w).disabled_types == ("duplicate", "formulation")
    assert (
        api().set_preferences(
            w["runtime"], **(c | {"disabled_types": ["duplicate", "formulation"]})
        )
        == two
    )
    assert counts(w) == (1, 0, 2)


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_commands_commit_once_or_cas_conflict(prefs_world, same_key):
    w = prefs_world
    barrier = Barrier(2)
    first = command(w)
    second = first if same_key else command(w)

    def apply(body):
        barrier.wait(timeout=3)
        try:
            return api().set_hidden(w["runtime"], **body)
        except DocumentError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(apply, [first, second]))
    if same_key:
        assert outcomes[0] == outcomes[1] and outcomes[0].revision == 1
    else:
        assert sum(v == "preferences_conflict" for v in outcomes) == 1
        assert sum(getattr(v, "revision", None) == 1 for v in outcomes) == 1
    assert state(w).revision == 1 and counts(w) == (1, 1, 1)


@pytest.mark.parametrize("after", [False, True])
def test_commit_failure_replay_resolves_actual_outcome(prefs_world, monkeypatch, after):
    w = prefs_world
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

    c = command(w)
    event.listen(w["engine"], "before_cursor_execute", mark)
    try:
        with monkeypatch.context() as m:
            m.setattr(w["engine"].dialect, "do_commit", commit)
            reject("storage_unavailable", lambda: api().set_hidden(w["runtime"], **c))
    finally:
        event.remove(w["engine"], "before_cursor_execute", mark)
    assert state(w).revision == (1 if after else 0)
    confirmed = api().set_hidden(w["runtime"], **c)
    assert confirmed.revision == 1 and confirmed.changed is True
    assert counts(w) == (1, 1, 1)


@pytest.mark.parametrize("field", ["command_data", "response_data"])
def test_corrupt_receipt_never_returns_or_reapplies_ack(prefs_world, field):
    w = prefs_world
    c = command(w)
    api().set_hidden(w["runtime"], **c)
    with w["engine"].begin() as conn:
        conn.execute(text(f"UPDATE {R} SET {field}=:data"), dict(data=b"SYNTHETIC_PRIVATE"))
    reject("storage_error", lambda: api().set_hidden(w["runtime"], **c))
    assert state(w).revision == 1 and counts(w) == (1, 1, 1)


@pytest.mark.parametrize(
    "table,column",
    [
        ("docx_analysis_sources", "source_data"),
        ("docx_analysis_attempts", "request_data"),
        ("docx_analysis_results", "result_data"),
        ("docx_analysis_results", "reply_data"),
    ],
)
def test_invalid_origin_never_creates_preference_rows(prefs_world, table, column):
    w = prefs_world
    with w["engine"].begin() as conn:
        conn.execute(text(f"UPDATE {table} SET {column}=:data"), dict(data=b"SYNTHETIC_PRIVATE"))
    reject("storage_error", lambda: api().set_hidden(w["runtime"], **command(w)))
    assert counts(w) == (0, 0, 0)


def test_foreign_scope_unknown_finding_and_changed_result_are_rejected(prefs_world):
    w = prefs_world
    for scope in ("peer", "foreign"):
        reject(
            "not_found",
            lambda: api().get_state(w["world"]["runtimes"][scope], document_id=w["doc"]),
        )
        reject("not_found", lambda: api().set_hidden(w["world"]["runtimes"][scope], **command(w)))
    other = seed(w["world"])
    reject(
        "not_found",
        lambda: api().set_hidden(w["runtime"], **command(w, document_id=other.document_id)),
    )
    reject(
        "not_found",
        lambda: api().set_hidden(w["runtime"], **command(w, finding_id="df-" + "0" * 64)),
    )
    reject(
        "preferences_conflict",
        lambda: api().set_hidden(w["runtime"], **command(w, result_sha256="0" * 64)),
    )
    assert counts(w) == (0, 0, 0)


def test_ownership_change_after_decode_prevents_write_and_no_lock_is_held(prefs_world, monkeypatch):
    w = prefs_world
    commands = importlib.import_module("ara.docx_review_preferences._commands")
    original = commands.finding_keys

    def transfer(*args, **kwargs):
        result = original(*args, **kwargs)
        with w["engine"].begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout='300ms'"))
            conn.execute(
                text("UPDATE projects SET owner_id=:owner WHERE id=:project"),
                dict(
                    owner=w["world"]["runtimes"]["foreign"].user_id, project=w["runtime"].project_id
                ),
            )
        return result

    monkeypatch.setattr(commands, "finding_keys", transfer)
    reject("not_found", lambda: api().set_hidden(w["runtime"], **command(w)))
    assert counts(w) == (0, 0, 0)


@pytest.mark.parametrize(
    "changes",
    [
        dict(expected_revision=True),
        dict(expected_revision=-1),
        dict(command_id="bad"),
        dict(disabled_types=["unknown"]),
        dict(disabled_types=["duplicate", "duplicate"]),
        dict(show_questions=1),
        dict(show_hidden="false"),
    ],
)
def test_invalid_command_is_safe_before_mutation(prefs_world, changes):
    w = prefs_world
    reject("validation_error", lambda: api().set_preferences(w["runtime"], **prefs(w, **changes)))
    assert counts(w) == (0, 0, 0)


def test_revision_overflow_is_rejected_but_old_ack_can_be_read(prefs_world):
    w = prefs_world
    c = prefs(w)
    first = api().set_preferences(w["runtime"], **c)
    with w["engine"].begin() as conn:
        conn.execute(text(f"UPDATE {P} SET revision=9223372036854775807"))
    reject(
        "preferences_history_exhausted",
        lambda: api().set_preferences(w["runtime"], **prefs(w, expected_revision=2**63 - 1)),
    )
    assert api().set_preferences(w["runtime"], **c) == first
    assert state(w).revision == 2**63 - 1 and counts(w) == (1, 0, 1)


def test_previous_schema_refused_without_automatic_migration(empty_pg_engine, apply_migrations):
    api()
    engine = empty_pg_engine
    apply_migrations(engine, "0012_docx_continuous_timeout")
    with engine.begin() as conn:
        doc, project, owner = parents(conn)
    runtime = DocumentRuntime(engine=engine, user_id=owner, project_id=project, mode="local")
    reject("preferences_schema_unavailable", lambda: api().get_state(runtime, document_id=doc))
    with engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT version_num FROM alembic_version"))
            == "0012_docx_continuous_timeout"
        )


def test_active_hide_budget_never_truncates_or_partially_commits(prefs_world):
    w = prefs_world
    api().set_hidden(w["runtime"], **command(w))
    current_key = state(w).hidden_keys[0]
    api().set_hidden(w["runtime"], **command(w, expected_revision=1, hidden=False))
    # Synthetic committed metadata fills the capacity without thousands of ML runs.
    keys = ["dh-" + f"{i:064x}" for i in range(10001)]
    keys = [key for key in keys if key != current_key][:10000]
    with w["engine"].begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {D}(document_id,dismissal_key,source_run_id,source_result_sha256,"
                "source_finding_id,hidden_at_revision) VALUES (:doc,:key,:run,:sha,:finding,2)"
            ),
            [
                dict(doc=w["doc"], key=key, run=w["run"], sha=w["sha"], finding=w["finding"])
                for key in keys
            ],
        )
    reject(
        "preferences_limit_exceeded",
        lambda: api().set_hidden(w["runtime"], **command(w, expected_revision=2)),
    )
    saved = state(w)
    assert saved.revision == 2 and len(saved.hidden_keys) == 10000
    assert current_key not in saved.hidden_keys and counts(w) == (1, 10000, 2)


def test_old_ack_replay_does_not_require_decoding_origin_again(prefs_world, monkeypatch):
    w = prefs_world
    c = command(w)
    first = api().set_hidden(w["runtime"], **c)
    commands = importlib.import_module("ara.docx_review_preferences._commands")

    def forbidden(*args, **kwargs):
        raise AssertionError("Old committed intent must not decode the origin again")

    monkeypatch.setattr(commands, "finding_keys", forbidden)
    assert api().set_hidden(w["runtime"], **c) == first and counts(w) == (1, 1, 1)


def test_record_change_after_validation_prevents_hidden_state_commit(prefs_world, monkeypatch):
    w = prefs_world
    commands = importlib.import_module("ara.docx_review_preferences._commands")
    original = commands.finding_keys

    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        with w["engine"].begin() as conn:
            conn.execute(
                text("UPDATE docx_analysis_results SET reply_data=:data"),
                dict(data=b"SYNTHETIC_PRIVATE"),
            )
        return result

    monkeypatch.setattr(commands, "finding_keys", change)
    reject("storage_error", lambda: api().set_hidden(w["runtime"], **command(w)))
    assert counts(w) == (0, 0, 0)


def test_same_command_uuid_is_isolated_by_document(prefs_world):
    w = prefs_world
    other = seed(w["world"])
    c = prefs(w, disabled_types=["formulation"])
    first = api().set_preferences(w["runtime"], **c)
    second = api().set_preferences(w["runtime"], **(c | {"document_id": other.document_id}))
    assert first.document_id != second.document_id and first.revision == second.revision == 1
    assert counts(w) == (2, 0, 2)


def test_running_analysis_is_not_a_valid_hide_origin(prefs_world):
    from test_docx_analysis_http import poll, started
    from test_docx_analysis_supervisor_runtime import wait_for

    w = prefs_world
    w["platform"].done.clear()
    location, _ = started(w["http"], w["item"], w["body"] | {"client_request_id": str(uuid4())})
    try:
        wait_for(lambda: w["platform"].launches == 2)
        run = UUID(w["http"].get(location).json()["run_id"])
        reject("result_not_ready", lambda: api().set_hidden(w["runtime"], **command(w, run_id=run)))
        assert counts(w) == (0, 0, 0)
    finally:
        w["http"].post(location + "/stop", json={})
        w["platform"].done.set()
    assert poll(w["http"], location)["state"]["status"] == "cancelled"


@pytest.mark.parametrize("edited", [False, True])
def test_repeat_source_reuses_key_but_edited_source_needs_new_hide(prefs_world, edited):
    from test_docx_analysis_http import poll, saved_request, started
    from test_docx_editor_http import command as edit_command
    from test_docx_editor_http import path

    w = prefs_world
    api().set_hidden(w["runtime"], **command(w))
    first_keys = state(w).hidden_keys
    body = w["body"] | {"client_request_id": str(uuid4())}
    if edited:
        response = w["http"].post(
            path(w["item"], w["view"]) + "/commands",
            json=edit_command(w["view"], "insert_text", "Changed "),
        )
        assert response.status_code == 200
        _, body = saved_request(w["http"], w["item"], response.json())
    receipt = poll(w["http"], started(w["http"], w["item"], body)[0])
    assert receipt["state"]["status"] == "succeeded"
    result = w["http"].get(root(w["item"]) + "/analysis-result").json()
    assert state(w).hidden_keys == first_keys
    second = api().set_hidden(
        w["runtime"],
        **command(
            w,
            expected_revision=1,
            run_id=UUID(receipt["run_id"]),
            result_sha256=result["stored_result_sha256"],
            finding_id=result["result"]["findings"][0]["finding_id"],
        ),
    )
    assert second.changed is edited and second.revision == 2
    assert len(state(w).hidden_keys) == (2 if edited else 1)
    assert counts(w) == (1, 2 if edited else 1, 2)


def test_inconsistent_hidden_revision_is_not_returned_as_valid_state(prefs_world):
    w = prefs_world
    api().set_hidden(w["runtime"], **command(w))
    with w["engine"].begin() as conn:
        conn.execute(text(f"UPDATE {D} SET hidden_at_revision=2"))
    reject("storage_error", lambda: state(w))
    assert counts(w) == (1, 1, 1)


def test_unhide_already_visible_is_a_durable_noop(prefs_world):
    w = prefs_world
    c = command(w, hidden=False)
    receipt = api().set_hidden(w["runtime"], **c)
    assert receipt.changed is False and receipt.revision == 1 and receipt.kind == "unhide"
    assert api().set_hidden(w["runtime"], **c) == receipt and counts(w) == (1, 0, 1)


@pytest.mark.parametrize(
    "changes",
    [dict(run_id="bad"), dict(hidden=1), dict(finding_id="df-short"), dict(result_sha256="G" * 64)],
)
def test_invalid_hide_locator_never_mutates_state(prefs_world, changes):
    w = prefs_world
    reject("validation_error", lambda: api().set_hidden(w["runtime"], **command(w, **changes)))
    assert counts(w) == (0, 0, 0)


@pytest.mark.parametrize("field", ["command_data", "response_data"])
def test_receipt_json_identity_is_checked_even_when_hash_matches(prefs_world, field):
    import json
    from hashlib import sha256

    w = prefs_world
    c = command(w)
    api().set_hidden(w["runtime"], **c)
    with w["engine"].begin() as conn:
        original = bytes(conn.scalar(text(f"SELECT {field} FROM {R}")))
        changed = json.loads(original)
        changed["document_id"] = str(uuid4())
        raw = json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
        hash_field = "command_sha256" if field == "command_data" else "response_sha256"
        conn.execute(
            text(f"UPDATE {R} SET {field}=:data,{hash_field}=:digest"),
            dict(data=raw, digest=sha256(raw).hexdigest()),
        )
    reject("storage_error", lambda: api().set_hidden(w["runtime"], **c))
    assert counts(w) == (1, 1, 1) and state(w).revision == 1
