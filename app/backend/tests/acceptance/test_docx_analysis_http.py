"""D: HTTP admission receipts are distinct from durable analysis and Stop intent."""

import base64
import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_docx_analysis_supervisor_runtime import FixturePlatform, wait_for
from test_docx_editor_http import control, opened, path, root
from test_docx_text_edit import seed

from ara.app import create_app
from ara.config import ConfigurationError, DatabaseSettings
from ara.docx_analysis_worker.review_fixture import fixture_execution, reply_for
from ara.docx_analysis_worker.supervisor import ledger
from ara.docx_analysis_worker.supervisor.runtime import _create_supervisor
from ara.docx_analysis_worker.wire import StreamDecoder, WireBinding, encode_message


class ReviewPlatform(FixturePlatform):
    """Synthetic port; a separate test runs the real native child."""

    def launch(self, slot, identity, budget, *, request, execution_spec):
        binding = WireBinding(identity.run_id, identity.attempt_id)
        frame = encode_message(
            binding,
            kind="run",
            seq=0,
            values=dict(
                worker_instance_id=str(identity.worker_instance_id),
                claim_fence=identity.claim_fence,
                request_sha256=sha256(request).hexdigest(),
                execution_spec_sha256=sha256(execution_spec).hexdigest(),
                request_b64=base64.b64encode(request).decode(),
                execution_spec_b64=base64.b64encode(execution_spec).decode(),
            ),
        )
        decoder = StreamDecoder(binding, lane="request")
        (message,) = decoder.feed(frame)
        decoder.finish()
        self.raw = reply_for(message)
        return super().launch(
            slot, identity, budget, request=request, execution_spec=execution_spec
        )


def build(world, tmp_path, *, native=False):
    runtime = world["runtimes"]["own"]
    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )
    kwargs = dict(
        settings=DatabaseSettings(world["engine"].url.render_as_string(hide_password=False)),
        user_id=runtime.user_id,
        project_id=runtime.project_id,
        installation_id=installation,
        root=tmp_path,
    )
    platform = ReviewPlatform(b"")
    if native:
        from ara.docx_analysis_worker.supervisor.review_fixture import (
            create_review_fixture_supervisor,
        )

        supervisor = create_review_fixture_supervisor(**kwargs)
    else:
        supervisor = _create_supervisor(**kwargs, execution=fixture_execution(), platform=platform)
    return supervisor, platform


@pytest.fixture
def api_world(run_world, tmp_path):
    # Import must fail red until the independent transport exists.
    importlib.import_module("ara.docx_analysis_api")
    s, p = build(run_world, tmp_path)
    item = seed(run_world)
    app = create_app(document_runtime=run_world["runtimes"]["own"], analysis_supervisor=s)
    assert s.view().phase == "new" and p.trace == []
    s.start()
    wait_for(lambda: s.view().phase == "ready")
    try:
        with TestClient(app) as http:
            yield run_world, item, app, http, s, p
    finally:
        p.done.set()
        p.cleaned.set()
        p.launch_gate.set()
        assert s.shutdown(timeout=5)


def saved_request(http, item, view=None):
    if view is None:
        view, _ = opened(http, item)
    save = control(view)
    response = http.post(path(item, view) + "/save", json=save)
    assert response.status_code == 200, response.text
    view = response.json()
    return view, dict(
        client_request_id=str(uuid4()),
        registry_id=view["registry_id"],
        session_id=view["session_id"],
        save_command_id=save["command_id"],
        command_sequence=view["command_sequence"],
        session_revision=view["document"]["session_revision"],
        storage_revision=view["base_storage_revision"],
        source_sha256=view["base_sha256"],
    )


def poll(http, location, phase="finished"):
    def get():
        response = http.get(location)
        assert response.status_code == 200, response.text
        value = response.json()
        return value if value["phase"] == phase else None

    return wait_for(get)


def started(http, item, body):
    response = http.post(root(item) + "/analysis-runs", json=body)
    assert response.status_code == 202, response.text
    assert response.headers["cache-control"] == "no-store"
    location = response.headers["location"]
    assert location == root(item) + "/analysis-requests/" + body["client_request_id"]
    return location, response.json()


def complete(api_world):
    world, item, app, http, s, p = api_world
    view, body = saved_request(http, item)
    location, _ = started(http, item, body)
    result = poll(http, location)
    assert result["state"]["status"] == "succeeded", result
    return view, body, location, result


def test_save_admit_poll_replay_and_freshness(api_world):
    world, item, app, http, s, p = api_world
    view, body, location, receipt = complete(api_world)
    assert receipt["schema_version"] == "docx-analysis-http/1" and receipt["fixture"] is True
    assert receipt["state"]["storage_revision"] == body["storage_revision"]
    result = http.get(root(item) + "/analysis-result")
    assert result.status_code == 200, result.text
    output = result.json()
    assert output["matches_saved_document"] is True and output["fixture"] is True
    assert output["result"]["findings"][0]["primary"]["quote"] == "Device 🧪"
    assert "private_provenance" not in output["result"]
    assert (
        http.get(root(item) + "/analysis-runs/" + receipt["run_id"]).json()["run"]["status"]
        == "succeeded"
    )
    assert http.post(path(item, view) + "/close", json=control(view)).status_code == 200
    assert started(http, item, body)[1]["run_id"] == receipt["run_id"]
    assert p.launches == 1
    with TestClient(
        create_app(document_runtime=world["runtimes"]["own"], analysis_supervisor=s)
    ) as other:
        assert other.get(location).json()["run_id"] == receipt["run_id"]
        assert poll(other, started(other, item, body)[0])["run_id"] == receipt["run_id"]
    assert p.launches == 1


def test_pending_receipt_stop_does_not_wait_for_save_provider(api_world, monkeypatch):
    world, item, app, http, s, p = api_world
    _, body = saved_request(http, item)
    entered, release = Event(), Event()
    original = app.state.docx_editor_registry.saved_target

    def delayed(**kwargs):
        entered.set()
        assert release.wait(10)
        return original(**kwargs)

    monkeypatch.setattr(app.state.docx_editor_registry, "saved_target", delayed)
    try:
        location, receipt = started(http, item, body)
        assert entered.wait(3)
        assert receipt["phase"] == "admitting" and receipt["run_id"] is None
        assert receipt["state"] is None
        stopped = http.post(location + "/stop", json={})
        assert stopped.status_code == 202 and stopped.json()["stop_requested"] is True
        assert stopped.json()["state"] is None
        assert started(http, item, body)[1]["stop_requested"] is True
    finally:
        release.set()
    assert poll(http, location)["state"]["status"] == "cancelled"
    assert p.launches == 0
    with world["engine"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM docx_analysis_sources")) == 1
        assert c.scalar(text("SELECT count(*) FROM docx_analysis_results")) == 0


def test_changed_key_body_and_foreign_scope(api_world):
    world, item, app, http, s, p = api_world
    _, body, location, receipt = complete(api_world)
    changed = dict(body, source_sha256="0" * 64)
    assert http.post(root(item) + "/analysis-runs", json=changed).status_code == 409
    foreign = seed(world, scope="foreign")
    for suffix in (
        "/analysis-result",
        "/analysis-runs/" + receipt["run_id"],
        "/analysis-requests/" + body["client_request_id"],
    ):
        assert http.get(root(foreign) + suffix).status_code == 404
    assert http.post(root(foreign) + "/analysis-runs", json=body).status_code == 404
    assert (
        http.post(
            root(foreign) + "/analysis-requests/" + body["client_request_id"] + "/stop", json={}
        ).status_code
        == 404
    )
    assert p.launches == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("save_command_id", str(uuid4())),
        ("command_sequence", "99"),
        ("session_revision", "99"),
        ("registry_id", str(uuid4())),
        ("source_sha256", "0" * 64),
    ],
)
def test_unconfirmed_target_never_runs_and_explicit_retry_can_reject_again(api_world, field, value):
    _, item, _, http, _, p = api_world
    _, body = saved_request(http, item)
    body[field] = value
    location, _ = started(http, item, body)
    result = poll(http, location, "not_admitted")
    assert result["run_id"] is None and result["error_code"]
    assert poll(http, started(http, item, body)[0], "not_admitted")["error_code"]
    assert p.launches == 0


@pytest.mark.parametrize(
    "fault,status",
    [
        ("duplicate", 422),
        ("extra", 422),
        ("bool", 422),
        ("zero", 422),
        ("negative", 422),
        ("nan", 422),
        ("uppercase", 422),
        ("query", 422),
        ("encoding", 415),
        ("media", 415),
        ("large", 413),
    ],
)
def test_strict_transport(api_world, fault, status):
    _, item, _, http, _, p = api_world
    _, body = saved_request(http, item)
    target = root(item) + "/analysis-runs"
    headers = {"Content-Type": "application/json"}
    if fault == "extra":
        body["private"] = "SYNTHETIC_PRIVATE"
    elif fault in ("bool", "zero", "negative", "nan"):
        body["command_sequence"] = dict(bool=True, zero="01", negative="-1", nan=float("nan"))[
            fault
        ]
    elif fault == "uppercase":
        body["client_request_id"] = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
    elif fault == "query":
        target += "?private=SYNTHETIC_PRIVATE"
    elif fault == "encoding":
        headers["Content-Encoding"] = "gzip"
    elif fault == "media":
        headers["Content-Type"] = "text/plain"
    raw = json.dumps(body).encode()
    if fault == "duplicate":
        raw = raw[:-1] + b',"source_sha256":"SYNTHETIC_PRIVATE"}'
    elif fault == "large":
        raw = b"x" * 65537
    response = http.post(target, content=raw, headers=headers)
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "SYNTHETIC_PRIVATE" not in response.text and p.launches == 0


def test_get_bodies_retry_body_and_no_current_result(api_world):
    _, item, _, http, _, _ = api_world
    assert http.get(root(item) + "/analysis-result").status_code == 404
    assert http.request("GET", root(item) + "/analysis-result", content="{}").status_code == 422
    assert http.get(root(item) + "/analysis-result?foo=1").status_code == 422
    assert (
        http.post(
            root(item) + "/analysis-runs/" + str(uuid4()) + "/retry",
            json={"client_request_id": str(uuid4()), "extra": True},
        ).status_code
        == 422
    )
    assert (
        http.post(
            root(item) + "/analysis-requests/" + str(uuid4()) + "/stop", json={"extra": True}
        ).status_code
        == 422
    )


def test_two_read_gates_do_not_block_stop(api_world, monkeypatch):
    _, item, app, http, _, p = api_world
    _, body = saved_request(http, item)
    p.done.clear()
    location, _ = started(http, item, body)
    wait_for(lambda: p.entered.is_set())
    reads = importlib.import_module("ara.docx_analysis_api._reads")
    original = reads.get_run
    entered = [Event(), Event()]
    release = Event()

    def blocked(*args, **kwargs):
        for event in entered:
            if not event.is_set():
                event.set()
                break
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(reads, "get_run", blocked)
    run_id = http.get(location).json()["run_id"]
    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [
                pool.submit(http.get, root(item) + "/analysis-runs/" + run_id) for _ in range(2)
            ]
            assert all(event.wait(3) for event in entered)
            response = http.get(root(item) + "/analysis-result")
            assert response.status_code == 503 and response.json()["code"] == "analysis_busy"
            stopped = http.post(location + "/stop", json={})
            assert stopped.status_code == 202 and stopped.json()["stop_requested"] is True
            release.set()
            assert all(f.result().status_code == 200 for f in futures)
    finally:
        release.set()
        p.done.set()
    assert poll(http, location)["state"]["status"] == "cancelled"


def test_known_stop_needs_no_sql(api_world, monkeypatch):
    _, item, _, http, _, p = api_world
    _, body = saved_request(http, item)
    p.done.clear()
    location, _ = started(http, item, body)
    wait_for(lambda: p.entered.is_set())
    reads = importlib.import_module("ara.docx_analysis_api._reads")

    def forbidden(*args, **kwargs):
        raise AssertionError("Known Stop must not wait for SQL")

    with monkeypatch.context() as m:
        m.setattr(reads, "scope_check", forbidden)
        m.setattr(reads, "get_request", forbidden)
        response = http.post(location + "/stop", json={})
        assert response.status_code == 202 and response.json()["stop_requested"] is True
    p.done.set()
    assert poll(http, location)["state"]["status"] == "cancelled"


def test_install_requires_matching_explicit_scope_and_no_implicit_start(run_world, tmp_path):
    importlib.import_module("ara.docx_analysis_api")
    s, p = build(run_world, tmp_path)
    runtime = run_world["runtimes"]["own"]
    with pytest.raises(ConfigurationError):
        create_app(analysis_supervisor=s)
    with pytest.raises(ConfigurationError):
        create_app(document_runtime=replace(runtime, project_id=uuid4()), analysis_supervisor=s)
    with pytest.raises(ConfigurationError):
        create_app(document_runtime=runtime, analysis_supervisor=object())
    app = create_app(document_runtime=runtime, analysis_supervisor=s)
    from ara.docx_analysis_api import install_analysis

    with pytest.raises(ConfigurationError):
        install_analysis(app, runtime, s)
    assert s.view().phase == "new" and p.trace == []
    schema = app.openapi()
    operation = schema["paths"]["/docx-documents/{document_id}/analysis-runs"]["post"]
    assert "202" in operation["responses"] and "requestBody" in operation
    assert s.shutdown(timeout=5)


def test_same_key_placeholder_coalesces_concurrent_post_and_stop(api_world, monkeypatch):
    _, item, _, http, s, p = api_world
    _, body = saved_request(http, item)
    entered, release = Event(), Event()
    original = s.admit_saved
    calls = []
    p.done.clear()

    def delayed(**kwargs):
        calls.append(kwargs["client_request_id"])
        ticket = original(**kwargs)
        entered.set()
        assert release.wait(10)
        return ticket

    monkeypatch.setattr(s, "admit_saved", delayed)
    location = root(item) + "/analysis-requests/" + body["client_request_id"]
    try:
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(started, http, item, body)
            assert entered.wait(3)
            other = started(http, item, body)[1]
            assert other["phase"] == "admitting" and other["run_id"] is None
            stopped = http.post(location + "/stop", json={})
            assert stopped.status_code == 202 and stopped.json()["stop_requested"]
            release.set()
            assert first.result()[1]["stop_requested"]
        wait_for(lambda: p.stopped.is_set() or p.launches == 0)
    finally:
        release.set()
        p.done.set()
    assert poll(http, location)["state"]["status"] == "cancelled"
    assert len(calls) == 1


def test_unknown_enqueue_ack_retains_receipt_until_reconciled(api_world, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from ara.docx_analysis_runs import _storage

    _, item, _, http, _, p = api_world
    _, body = saved_request(http, item)
    original = _storage.enqueue
    entered, release = Event(), Event()

    def lost_ack(*args, **kwargs):
        original(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        raise OperationalError("COMMIT", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    monkeypatch.setattr(_storage, "enqueue", lost_ack)
    try:
        location, _ = started(http, item, body)
        assert entered.wait(3)
        receipt = http.get(location).json()
        assert receipt["phase"] == "admitting" and receipt["state"] is None
        assert http.post(location + "/stop", json={}).json()["stop_requested"]
    finally:
        release.set()
    assert poll(http, location)["state"]["status"] == "cancelled"
    assert p.launches == 0


def test_stop_gate_is_separate_and_bounded(api_world, monkeypatch):
    _, item, app, http, _, _ = api_world
    _, _, location, receipt = complete(api_world)
    service = app.state.docx_analysis_service
    original = service.stop
    entered, release = Event(), Event()

    def delayed(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(service, "stop", delayed)
    try:
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(http.post, location + "/stop", json={})
            assert entered.wait(3)
            assert http.post(location + "/stop", json={}).status_code == 503
            assert http.get(location).json()["run_id"] == receipt["run_id"]
            release.set()
            terminal = pending.result()
            assert terminal.status_code == 202 and not terminal.json()["stop_requested"]
            assert terminal.json()["state"]["status"] == "succeeded"
    finally:
        release.set()


def test_terminal_receipt_eviction_falls_back_to_sql_without_inference(api_world):
    _, item, app, http, _, p = api_world
    _, body, location, receipt = complete(api_world)
    service = app.state.docx_analysis_service
    # Populate many completed negative intents through the real admission lane.
    for _ in range(130):
        bad = dict(body, client_request_id=str(uuid4()), save_command_id=str(uuid4()))
        poll(http, started(http, item, bad)[0], "not_admitted")
    assert len(service._entries) <= 145
    assert all(not hasattr(entry, "source_data") for entry in service._entries.values())
    assert http.get(location).json()["run_id"] == receipt["run_id"]
    assert poll(http, started(http, item, body)[0])["run_id"] == receipt["run_id"]
    assert p.launches == 1
