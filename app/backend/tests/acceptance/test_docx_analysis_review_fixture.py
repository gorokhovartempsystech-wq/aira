"""C2 semantic fixture through real wire, B1/SQL and available native processes."""

import base64
import importlib
import json
import sys
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_analysis_runs_start import world as world
from test_docx_analysis_storage_codec import command
from test_docx_analysis_supervisor_runtime import finished, submit, wait_for
from test_docx_review_v1 import fixture

from ara.config import DatabaseSettings
from ara.docx_analysis.storage_codec import capture_result, capture_source, prepare_attempt
from ara.docx_analysis_worker.supervisor import ledger
from ara.docx_analysis_worker.wire import StreamDecoder, WireBinding, encode_message


def api():
    return importlib.import_module("ara.docx_analysis_worker.review_fixture")


def supervisor():
    return importlib.import_module("ara.docx_analysis_worker.supervisor.review_fixture")


def prepared():
    raw, snapshot = fixture()
    source = capture_source(
        raw, snapshot, command=command(snapshot), execution=api().fixture_execution()
    )
    attempt = prepare_attempt(source, attempt_id=uuid4())
    binding = WireBinding(uuid4(), attempt.attempt_id)
    frame = encode_message(
        binding,
        kind="run",
        seq=0,
        values=dict(
            worker_instance_id=str(uuid4()),
            claim_fence=1,
            request_sha256=attempt.request_sha256,
            execution_spec_sha256=source.execution_spec_sha256,
            request_b64=base64.b64encode(attempt.request_data).decode(),
            execution_spec_b64=base64.b64encode(source.execution_spec).decode(),
        ),
    )
    decoder = StreamDecoder(binding, lane="request")
    (message,) = decoder.feed(frame)
    decoder.finish()
    return source, attempt, message


def changed(message, body):
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    values = dict(message.values, request_sha256=sha256(raw).hexdigest())
    return replace(message, payload=raw, values=values)


def test_fixture_reply_passes_real_source_validation_and_is_clearly_synthetic():
    source, attempt, request = prepared()
    reply = api().reply_for(request)
    result = capture_result(source, attempt, reply=reply)
    assert result.findings_count == 1 and result.questions_count == 1
    assert result.no_findings is False
    view = json.loads(result.result_data)
    assert view["provenance"]["execution_kind"] == "fixture"
    (finding,) = view["findings"]
    assert "Учебный пример" in finding["explanation"]
    assert "Учебный пример" in finding["question"]
    original = json.loads(request.payload)["engine_request"]["fragments"][0]
    assert finding["primary"]["quote"] == original["text"][:64]
    assert finding["primary"]["start"] == 0
    assert api().reply_for(request) == reply


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "spec_hash",
        "attempt",
        "kind",
        "version",
        "extra",
        "local_model",
        "profile",
        "policy",
        "source",
        "source_revision",
        "snapshot",
        "filters",
        "dismissed",
        "no_fragments",
        "duplicate",
        "text",
        "id",
        "status",
        "offset",
        "count",
        "budget",
        "duplicate_json",
    ],
)
def test_invalid_request_fails_without_payload_in_diagnostic(fault):
    _, _, request = prepared()
    body = json.loads(request.payload)
    fragments = body["engine_request"]["fragments"]
    if fault == "hash":
        request = replace(request, values=dict(request.values, request_sha256="0" * 64))
    elif fault == "spec_hash":
        request = replace(request, values=dict(request.values, execution_spec_sha256="0" * 64))
    elif fault == "attempt":
        request = replace(request, binding=WireBinding(request.binding.run_id, uuid4()))
    elif fault == "kind":
        request = replace(request, kind="result")
    elif fault == "duplicate_json":
        raw = b'{"kind":"PRIVATE","kind":"review_request"}'
        request = replace(
            request,
            payload=raw,
            values=dict(request.values, request_sha256=sha256(raw).hexdigest()),
        )
    else:
        if fault == "version":
            body["schema_version"] = "docx-review/2"
        if fault == "extra":
            body["PRIVATE"] = "PRIVATE"
        if fault == "local_model":
            body["provenance"]["execution_kind"] = "local_model"
        if fault == "profile":
            body["profile"] = "unknown"
        if fault == "policy":
            body["policy_version"] = "unknown"
        if fault == "source":
            body["source"]["document_id"] = "PRIVATE"
        if fault == "source_revision":
            body["source"]["storage_revision"] = "01"
        if fault == "snapshot":
            body["snapshot_sha256"] = "PRIVATE"
        if fault == "filters":
            body["engine_request"]["disabled_types"] = ["formulation"]
        if fault == "dismissed":
            body["engine_request"]["dismissed"] = ["iss-0123456789"]
        if fault == "no_fragments":
            body["engine_request"]["fragments"] = []
        if fault == "duplicate":
            fragments[1]["id"] = fragments[0]["id"]
        if fault == "text":
            fragments[0]["text"] = ""
        if fault == "id":
            fragments[0]["id"] = "PRIVATE"
        if fault == "status":
            fragments[0]["status"] = "deprecated"
        if fault == "offset":
            fragments[0]["offset"] = True
        if fault == "count":
            body["engine_request"]["fragments"] = fragments * 257
        if fault == "budget":
            fragments[0]["text"] = "a" * 1000001
        request = changed(request, body)
    with pytest.raises(api().ReviewFixtureError) as caught:
        api().reply_for(request)
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("kind", ["macos", "windows"])
@pytest.mark.parametrize("valid", [True, False])
def test_both_child_bodies_emit_real_wire_with_no_parent_replacement(monkeypatch, kind, valid):
    _, _, request = prepared()
    if not valid:
        request = replace(request, payload=b"PRIVATE")
    child = importlib.import_module("ara.docx_analysis_worker." + kind + "._fixture_child")
    frames = []
    if kind == "macos":

        def write(fd, data):
            assert fd == 1
            frames.append(bytes(data))
            return len(data)

        monkeypatch.setattr(child.os, "write", write)
        code = child.run_fixture(request.binding, request, "review")
    else:
        code = child.run_fixture(
            SimpleNamespace(), request.binding, request, "review", frames.append, 0
        )
    decoder = StreamDecoder(
        request.binding,
        lane="events",
        expected_execution_spec_sha256=request.values["execution_spec_sha256"],
    )
    messages = decoder.feed(b"".join(frames))
    decoder.finish()
    assert [m.kind for m in messages] == ["ready", "stage", "stage", "result" if valid else "error"]
    assert code == (0 if valid else 76)
    if valid:
        assert messages[-1].payload == api().reply_for(request)
    else:
        assert messages[-1].values["code"] == "adapter_error"
        assert b"PRIVATE" not in b"".join(frames)


def make(world, tmp_path, installation):
    w = world["scopes"]["own"]
    return supervisor().create_review_fixture_supervisor(
        settings=DatabaseSettings(world["engine"].url.render_as_string(hide_password=False)),
        user_id=w["runtime"].user_id,
        project_id=w["runtime"].project_id,
        installation_id=installation,
        root=tmp_path,
    )


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_native_review_success_restart_and_next_run(world, tmp_path):
    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )
    for run_number in (1, 2):
        s = make(world, tmp_path, installation)
        assert s.view().phase == "new" and s.view().fixture is True
        try:
            s.start()
            wait_for(lambda: s.view().phase == "ready")
            with world["engine"].connect() as conn:
                assert (
                    conn.scalar(text("SELECT count(*) FROM docx_analysis_results"))
                    == run_number - 1
                )
            ticket = submit(s, world)
            out = finished(s, ticket)
            assert out.sql_state.summary.status == "succeeded"
            assert out.sql_state.summary.execution_kind == "fixture"
            wait_for(lambda: ledger.read_fence(world["engine"]).phase == "clean")
            with world["engine"].connect() as conn:
                rows = conn.execute(
                    text("SELECT result_data,findings_count,no_findings FROM docx_analysis_results")
                ).all()
            assert len(rows) == run_number
            for row in rows:
                assert row.findings_count == 1 and row.no_findings is False
                assert (
                    json.loads(bytes(row.result_data))["provenance"]["models_version"]
                    == "aira-review-fixture-1"
                )
        finally:
            assert s.shutdown(timeout=5)


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_native_immediate_stop_preserves_source_without_result(world, tmp_path):
    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )
    s = make(world, tmp_path, installation)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        ticket = submit(s, world)
        s.stop(ticket)
        assert finished(s, ticket).sql_state.summary.status == "cancelled"
        with world["engine"].connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM docx_analysis_results")) == 0
            assert conn.scalar(text("SELECT count(*) FROM docx_analysis_sources")) == 1
    finally:
        assert s.shutdown(timeout=5)


def test_unsupported_host_never_falls_back_to_fake_platform(world, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "unsupported")
    from ara.docx_analysis_worker.supervisor._runtime_models import SupervisorError

    with pytest.raises(SupervisorError) as caught:
        make(world, tmp_path, uuid4())
    assert caught.value.code == "runtime_unavailable"
