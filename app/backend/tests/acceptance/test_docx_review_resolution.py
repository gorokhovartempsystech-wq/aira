"""E4B scoped resolution of actual persistent hides against a verified target."""

import importlib
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_review_preferences import counts, reject
from test_docx_review_remapping import TEXTS, records

from ara import docx_analysis_runs as runs
from ara import docx_documents as documents
from ara import docx_review_preferences as preferences
from ara.docx_analysis.storage_codec import decode_command, decode_execution
from ara.docx_editor._models import SavedTarget


def api():
    return importlib.import_module("ara.docx_review_resolution")


def analyze(w, texts=TEXTS, *, at=2, spec=None, finish=True):
    current = documents.get_docx(w["runtime"], document_id=w["doc"])
    prepared = records(
        texts, at=at, spec=spec, document_id=w["doc"], revision=current.storage_revision
    )
    if prepared[0].source_data != current.current_data:
        current = documents.save_docx(
            w["runtime"],
            document_id=w["doc"],
            expected_storage_revision=current.storage_revision,
            data=prepared[0].source_data,
        )
        prepared = records(
            texts, at=at, spec=spec, document_id=w["doc"], revision=current.storage_revision
        )
    src = prepared[0]
    command = decode_command(src.command_data, expected_sha256=src.command_sha256)
    execution = decode_execution(src.execution_spec, expected_sha256=src.execution_spec_sha256)
    target = SavedTarget(
        command.registry_id,
        command.document_id,
        command.session_id,
        command.save_command_id,
        command.command_sequence,
        command.session_revision,
        src.storage_revision,
        src.source_sha256,
        src.source_data,
    )
    admitted = runs.start_saved(
        w["runtime"],
        client_request_id=uuid4(),
        command=command,
        target_provider=lambda: target,
        execution=execution,
    )
    if not finish:
        return dict(run_id=admitted.summary.run_id, result_sha256="0" * 64, finding_id=None)
    claim = runs.claim_next(w["engine"], worker_instance_id=uuid4())
    assert claim.run_id == admitted.summary.run_id
    completed = runs.complete_attempt(w["engine"], claim, reply=prepared[2].reply_data)
    assert completed.accepted and completed.state.summary.status == "succeeded"
    with w["engine"].connect() as conn:
        row = conn.execute(
            text("SELECT result_sha256,result_data FROM docx_analysis_results WHERE run_id=:run"),
            dict(run=claim.run_id),
        ).one()
    return dict(
        run_id=claim.run_id,
        result_sha256=row.result_sha256,
        finding_id=json.loads(bytes(row.result_data))["findings"][0]["finding_id"],
    )


@pytest.fixture
def resolution_world(run_world):
    api()
    runtime = run_world["runtimes"]["own"]
    raw = records()[0].source_data
    item = documents.import_docx(
        runtime, document_id=uuid4(), title="Synthetic resolution", data=raw
    )
    w = dict(world=run_world, engine=run_world["engine"], runtime=runtime, doc=item.document_id)
    w["first"] = analyze(w)
    return w


def state(w):
    return preferences.get_state(w["runtime"], document_id=w["doc"])


def hide(w, origin):
    return preferences.set_hidden(
        w["runtime"],
        document_id=w["doc"],
        command_id=uuid4(),
        expected_revision=state(w).revision,
        hidden=True,
        **origin,
    )


def get(w, origin=None, *, runtime=None, **kwargs):
    target = origin or w["first"]
    return api().get_resolution(
        runtime or w["runtime"],
        document_id=w["doc"],
        run_id=target["run_id"],
        result_sha256=target["result_sha256"],
        **kwargs,
    )


def test_default_resolution_is_readonly_and_source_verified(resolution_world):
    w = resolution_world
    result = get(w)
    assert result.state.revision == 0 and result.hidden_keys == () and result.aliases == ()
    assert result.target.run_id == w["first"]["run_id"]
    assert len(result.finding_keys) == 1 and counts(w) == (0, 0, 0)
    assert "evidence" not in repr(result) and "Synthetic" not in repr(result)


def test_exact_source_repeated_attempt_and_reopen_preserve_resolution(resolution_world):
    w = resolution_world
    hide(w, w["first"])
    second = analyze(w)
    result = get(w, second)
    assert result.hidden_keys == state(w).hidden_keys
    assert len(result.aliases) == 1 and result.aliases[0].finding_id == second["finding_id"]
    assert result.aliases[0].origin_keys == state(w).hidden_keys
    assert get(w, second, runtime=replace(w["runtime"])) == result
    assert counts(w) == (1, 1, 1)


def test_far_edit_uses_new_key_without_mutating_original_hide(resolution_world):
    w = resolution_world
    hide(w, w["first"])
    original = state(w)
    target = analyze(w, ("New distant",) + TEXTS, at=3)
    result = get(w, target)
    assert len(result.hidden_keys) == 1 and result.hidden_keys != original.hidden_keys
    assert result.aliases[0].origin_keys == original.hidden_keys
    assert result.aliases[0].key == result.hidden_keys[0]
    assert state(w) == original and counts(w) == (1, 1, 1)


@pytest.mark.parametrize("changed", ["evidence", "model"])
def test_changed_evidence_or_model_keeps_new_finding_visible(resolution_world, changed):
    from test_docx_analysis_storage_codec import execution

    w = resolution_world
    hide(w, w["first"])
    target = (
        analyze(w, TEXTS[:2] + (TEXTS[2] + " changed",) + TEXTS[3:])
        if changed == "evidence"
        else analyze(w, spec=execution(models_version="synthetic-2"))
    )
    result = get(w, target)
    assert result.hidden_keys == () and result.aliases == ()
    assert len(state(w).hidden_keys) == 1 and counts(w) == (1, 1, 1)


def two_origins(w):
    hide(w, w["first"])
    second = analyze(w, ("Changed distant intro",) + TEXTS[1:])
    hide(w, second)
    target = analyze(w, ("Another distant intro",) + TEXTS[1:])
    return second, target


def test_all_old_decisions_resolving_to_same_finding_are_retained_as_aliases(resolution_world):
    w = resolution_world
    _, target = two_origins(w)
    result = get(w, target)
    assert len(result.hidden_keys) == len(result.aliases) == 1
    assert len(result.aliases[0].origin_keys) == 2
    assert result.aliases[0].origin_keys == state(w).hidden_keys
    assert len(result.decisions) == 2 and counts(w) == (1, 2, 2)


@pytest.mark.parametrize("scope", ["peer", "foreign"])
def test_foreign_scope_never_observes_resolution(resolution_world, scope):
    w = resolution_world
    hide(w, w["first"])
    reject("not_found", lambda: get(w, runtime=w["world"]["runtimes"][scope]))
    assert counts(w) == (1, 1, 1)


@pytest.mark.parametrize(
    "table,column",
    [
        ("docx_analysis_sources", "source_data"),
        ("docx_analysis_runs", "snapshot_data"),
        ("docx_analysis_attempts", "request_data"),
        ("docx_analysis_results", "reply_data"),
        ("docx_analysis_results", "result_data"),
    ],
)
def test_corrupt_old_origin_cannot_be_silently_skipped(resolution_world, table, column):
    w = resolution_world
    hide(w, w["first"])
    target = analyze(w, ("New intro",) + TEXTS[1:])
    with w["engine"].begin() as conn:
        if table == "docx_analysis_sources":
            where = "source_sha256=(SELECT source_sha256 FROM docx_analysis_runs WHERE id=:run)"
        else:
            where = "id=:run" if table == "docx_analysis_runs" else "run_id=:run"
        conn.execute(
            text(f"UPDATE {table} SET {column}=:bad WHERE {where}"),
            dict(bad=b"SYNTHETIC_PRIVATE", run=w["first"]["run_id"]),
        )
    reject("storage_error", lambda: get(w, target))
    assert counts(w) == (1, 1, 1)


@pytest.mark.parametrize(
    "column,value", [("dismissal_key", "dh-" + "0" * 64), ("source_finding_id", "df-" + "0" * 64)]
)
def test_valid_shape_but_wrong_origin_finding_or_key_is_corruption(resolution_world, column, value):
    w = resolution_world
    hide(w, w["first"])
    with w["engine"].begin() as conn:
        conn.execute(text(f"UPDATE docx_review_dismissals SET {column}=:value"), dict(value=value))
    reject("storage_error", lambda: get(w))
    assert counts(w) == (1, 1, 1)


@pytest.mark.parametrize("kind", ["origins", "bytes", "text"])
def test_resolution_limits_return_no_partial_keys_and_write_nothing(resolution_world, kind):
    w = resolution_world
    _, target = two_origins(w)
    options = {
        "origins": dict(max_origins=1),
        "bytes": dict(max_record_bytes=1),
        "text": dict(max_text_characters=1),
    }[kind]
    before = state(w)
    error = reject(
        "preferences_resolution_limit",
        lambda: get(w, target, limits=api().ResolutionLimits(**options)),
    )
    assert error.status == 413 and state(w) == before and counts(w) == (1, 2, 2)


def test_origin_count_is_checked_before_fetching_extra_blob_records(resolution_world, monkeypatch):
    w = resolution_world
    _, target = two_origins(w)
    loader = importlib.import_module("ara.docx_review_resolution._load")
    original = loader.records
    read = []

    def tracked(session, document_id, run_id, digest):
        read.append(run_id)
        assert run_id == target["run_id"], "Origin blobs fetched before budget admission"
        return original(session, document_id, run_id, digest)

    monkeypatch.setattr(loader, "records", tracked)
    reject(
        "preferences_resolution_limit",
        lambda: get(w, target, limits=api().ResolutionLimits(max_origins=1)),
    )
    assert read == [target["run_id"]]


@pytest.mark.parametrize("race", ["owner", "preferences"])
def test_decode_holds_no_sql_locks_and_scope_revision_is_checked_again(
    resolution_world, monkeypatch, race
):
    w = resolution_world
    hide(w, w["first"])
    module = importlib.import_module("ara.docx_review_resolution._resolve")
    original = module.match_findings

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if race == "owner":
            with w["engine"].begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout='500ms'"))
                conn.execute(
                    text("UPDATE projects SET owner_id=:owner WHERE id=:project"),
                    dict(
                        owner=w["world"]["runtimes"]["foreign"].user_id,
                        project=w["runtime"].project_id,
                    ),
                )
        else:
            preferences.set_preferences(
                w["runtime"],
                document_id=w["doc"],
                command_id=uuid4(),
                expected_revision=1,
                disabled_types=["formulation"],
                show_questions=True,
                show_hidden=False,
            )
        return result

    monkeypatch.setattr(module, "match_findings", changed)
    reject("not_found" if race == "owner" else "preferences_conflict", lambda: get(w))


def test_new_current_docx_does_not_retarget_pinned_resolution(resolution_world, monkeypatch):
    w = resolution_world
    hide(w, w["first"])
    module = importlib.import_module("ara.docx_review_resolution._resolve")
    original = module.match_findings

    def edit(*args, **kwargs):
        result = original(*args, **kwargs)
        current = documents.get_docx(w["runtime"], document_id=w["doc"])
        documents.save_docx(
            w["runtime"],
            document_id=w["doc"],
            expected_storage_revision=current.storage_revision,
            data=records(("Entirely new",) + TEXTS, at=3)[0].source_data,
        )
        return result

    monkeypatch.setattr(module, "match_findings", edit)
    result = get(w)
    assert result.hidden_keys == state(w).hidden_keys
    assert (
        result.target.source.source_sha256
        != documents.get_docx(w["runtime"], document_id=w["doc"]).current_sha256
    )


def test_recheck_for_future_writer_rejects_changed_origin_bytes(resolution_world):
    from ara.docx_review_preferences import _reads

    w = resolution_world
    hide(w, w["first"])
    _, target = two_origins_without_first_hide(w)
    result = get(w, target)
    with w["engine"].begin() as conn:
        conn.execute(
            text("UPDATE docx_analysis_results SET reply_data=:bad WHERE run_id=:run"),
            dict(bad=b"SYNTHETIC_PRIVATE", run=w["first"]["run_id"]),
        )
    loader = importlib.import_module("ara.docx_review_resolution._load")
    with _reads.transaction(w["runtime"], w["doc"], writing=True) as session:
        reject("storage_error", lambda: loader.recheck_inputs(session, result))
    assert counts(w) == (1, 2, 2)


def two_origins_without_first_hide(w):
    second = analyze(w, ("Changed distant intro",) + TEXTS[1:])
    hide(w, second)
    return second, analyze(w, ("Another distant intro",) + TEXTS[1:])


def test_pending_run_and_bad_hash_do_not_become_empty_success(resolution_world):
    w = resolution_world
    reject("preferences_conflict", lambda: get(w, w["first"] | dict(result_sha256="0" * 64)))
    pending = analyze(w, finish=False)
    reject("result_not_ready", lambda: get(w, pending))
    assert counts(w) == (0, 0, 0)


@pytest.mark.parametrize(
    "changes", [dict(run_id="bad"), dict(document_id="bad"), dict(result_sha256="A" * 64)]
)
def test_invalid_locator_is_rejected_before_storage(resolution_world, changes):
    w = resolution_world
    kwargs = (
        dict(
            document_id=w["doc"],
            run_id=w["first"]["run_id"],
            result_sha256=w["first"]["result_sha256"],
        )
        | changes
    )
    reject("validation_error", lambda: api().get_resolution(w["runtime"], **kwargs))
    assert counts(w) == (0, 0, 0)


def test_limits_require_exact_positive_bounded_integers():
    for value in (True, 0, 65):
        reject("validation_error", lambda: api().ResolutionLimits(max_origins=value))


def test_byte_admission_precedes_loading_additional_origin_buffers(resolution_world, monkeypatch):
    w = resolution_world
    hide(w, w["first"])
    target = analyze(w, ("New intro",) + TEXTS[1:])
    resolved = get(w, target)
    current = resolved.target
    maximum = sum(
        len(value)
        for value in (
            current.source.source_data,
            current.source.snapshot_data,
            current.source.command_data,
            current.source.execution_spec,
            current.attempt.request_data,
            current.result.reply_data,
            current.result.result_data,
        )
    )
    loader = importlib.import_module("ara.docx_review_resolution._load")
    original = loader.records
    read = []

    def checked(session, document_id, run_id, digest):
        read.append(run_id)
        assert run_id == target["run_id"]
        return original(session, document_id, run_id, digest)

    monkeypatch.setattr(loader, "records", checked)
    reject(
        "preferences_resolution_limit",
        lambda: get(w, target, limits=api().ResolutionLimits(max_record_bytes=maximum)),
    )
    assert read == [target["run_id"]] and counts(w) == (1, 1, 1)


def test_text_work_is_reserved_before_next_pairwise_validation(resolution_world, monkeypatch):
    w = resolution_world
    hide(w, w["first"])
    target = analyze(w, ("New intro",) + TEXTS[1:])
    resolved = get(w, target)
    maximum = len(json.loads(resolved.target.source.snapshot_data)["analysis_text"])
    module = importlib.import_module("ara.docx_review_resolution._resolve")

    def forbidden(*args, **kwargs):
        raise AssertionError("No remaining text work budget")

    monkeypatch.setattr(module, "match_findings", forbidden)
    reject(
        "preferences_resolution_limit",
        lambda: get(w, target, limits=api().ResolutionLimits(max_text_characters=maximum)),
    )
    assert counts(w) == (1, 1, 1)


def test_false_small_manifest_does_not_bypass_origin_validation(resolution_world):
    from hashlib import sha256

    from test_docx_review_v1 import canonical

    w = resolution_world
    hide(w, w["first"])
    target = analyze(w, ("New intro",) + TEXTS[1:])
    with w["engine"].begin() as conn:
        raw = bytes(
            conn.scalar(
                text("SELECT snapshot_data FROM docx_analysis_runs WHERE id=:run"),
                dict(run=w["first"]["run_id"]),
            )
        )
        manifest = json.loads(raw)
        manifest["analysis_text"] = ""
        bad = canonical(manifest)
        conn.execute(
            text(
                "UPDATE docx_analysis_runs SET snapshot_data=:raw,snapshot_sha256=:sha "
                "WHERE id=:run"
            ),
            dict(raw=bad, sha=sha256(bad).hexdigest(), run=w["first"]["run_id"]),
        )
    reject("storage_error", lambda: get(w, target))
    assert counts(w) == (1, 1, 1)


def test_current_result_is_validated_even_without_any_hide(resolution_world):
    w = resolution_world
    with w["engine"].begin() as conn:
        conn.execute(
            text("UPDATE docx_analysis_results SET result_data=:raw"),
            dict(raw=b"SYNTHETIC_PRIVATE"),
        )
    reject("storage_error", lambda: get(w))
    assert counts(w) == (0, 0, 0)


def test_recheck_detects_origin_reference_change_even_if_revision_is_unchanged(resolution_world):
    from ara.docx_review_preferences import _reads

    w = resolution_world
    hide(w, w["first"])
    second = analyze(w)
    result = get(w, second)
    with w["engine"].begin() as conn:
        conn.execute(
            text(
                "UPDATE docx_review_dismissals SET source_run_id=:run,source_result_sha256=:sha,"
                "source_finding_id=:finding"
            ),
            dict(run=second["run_id"], sha=second["result_sha256"], finding=second["finding_id"]),
        )
    loader = importlib.import_module("ara.docx_review_resolution._load")
    with _reads.transaction(w["runtime"], w["doc"], writing=True) as session:
        reject("storage_error", lambda: loader.recheck_inputs(session, result))
    assert counts(w) == (1, 1, 1)
