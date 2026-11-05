"""Independent dedicated-DB and HTTP license server acceptance; synthetic keys only."""

import asyncio
import importlib
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event, Lock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError
from test_licensing_policy import BASE, DEVICE, NONCE, OTHER, synthetic_key

from ara import licensing as core


def api():
    return importlib.import_module("ara.licensing.server")


def reject(code, call):
    with pytest.raises((core.LicenseError, api().ServerError)) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
    assert "SYNTHETIC_PRIVATE" not in repr(caught.value)


@pytest.fixture
def license_world(empty_pg_engine):
    a = api()
    a.initialize_database(empty_pg_engine)
    clock = [BASE]
    runtime = a.ServerRuntime(empty_pg_engine, secrets.token_bytes(32), lambda: clock[0])
    key, license_id = synthetic_key(), uuid4()
    issued = a.issue_license(runtime, license_id=license_id, key=key, duration_seconds=60)
    assert issued.device_id is None
    return dict(a=a, engine=empty_pg_engine, runtime=runtime, clock=clock, key=key, id=license_id)


def request(w, *, device=DEVICE, operation="activate", nonce=NONCE):
    identity = dict(license_key=w["key"]) if operation == "activate" else dict(license_id=w["id"])
    return core.StartRequest(operation, device, nonce, **identity)


def run(w, req=None):
    return core.decode_grant(w["a"].process_request(w["runtime"], req or request(w)))


def state(w):
    return w["a"].get_license(w["runtime"], license_id=w["id"])


def app(w):
    return w["a"].create_license_app(w["runtime"])


def post(client, req):
    return client.post(
        "/license/v1/" + req.operation,
        content=core.encode_request(req),
        headers={"Content-Type": "application/json"},
    )


def test_schema_is_separate_repeatable_and_has_no_plaintext_column(license_world):
    w = license_world
    original = state(w)
    w["a"].initialize_database(w["engine"])
    assert state(w) == original
    inspector = inspect(w["engine"])
    assert set(inspector.get_table_names()) == {"aira_license_schema", "aira_licenses"}
    assert {c["name"] for c in inspector.get_columns("aira_licenses")} == {
        "license_id",
        "key_digest",
        "duration_seconds",
        "enabled",
        "created_at_ms",
        "device_id",
        "activated_at_ms",
        "expires_at_ms",
    }
    with w["engine"].connect() as conn:
        assert conn.execute(text("SELECT id,revision FROM aira_license_schema")).all() == [(1, 1)]
        assert conn.scalar(text("SELECT key_digest FROM aira_licenses")) == core.key_digest(
            w["key"], w["runtime"].pepper
        )


@pytest.mark.parametrize("table", ["foreign_data", "aira_license_schema"])
def test_initializer_never_adopts_foreign_or_partial_database(empty_pg_engine, table):
    with empty_pg_engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (keep integer NOT NULL)"))
        conn.execute(text(f"INSERT INTO {table} VALUES (7)"))
    reject("license_schema_unavailable", lambda: api().initialize_database(empty_pg_engine))
    assert inspect(empty_pg_engine).get_table_names() == [table]
    with empty_pg_engine.connect() as conn:
        assert conn.scalar(text(f"SELECT keep FROM {table}")) == 7


def test_schema_initialization_rolls_back_as_a_unit(empty_pg_engine):
    def fail_marker(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().replace("public.", "").startswith("INSERT INTO aira_license_schema"):
            raise OSError("SYNTHETIC_PRIVATE")

    event.listen(empty_pg_engine, "before_cursor_execute", fail_marker)
    try:
        reject("license_storage_unavailable", lambda: api().initialize_database(empty_pg_engine))
    finally:
        event.remove(empty_pg_engine, "before_cursor_execute", fail_marker)
    assert inspect(empty_pg_engine).get_table_names() == []


@pytest.mark.parametrize(
    "assignment",
    [
        "duration_seconds=0",
        "key_digest='bad'",
        "device_id='bad'",
        "activated_at_ms=1",
        "expires_at_ms=-1",
        "created_at_ms=-1",
    ],
)
def test_database_rejects_invalid_license_states(license_world, assignment):
    w = license_world
    with pytest.raises(IntegrityError), w["engine"].begin() as conn:
        conn.execute(text("UPDATE aira_licenses SET " + assignment))
    assert state(w).device_id is None


def test_issue_repeat_keeps_activation_disabled_state_and_original_duration(license_world):
    w = license_world
    first = run(w)
    disabled = w["a"].set_enabled(w["runtime"], license_id=w["id"], enabled=False)
    w["clock"][0] += 10000
    again = w["a"].issue_license(
        w["runtime"], license_id=w["id"], key=w["key"].lower(), duration_seconds=60
    )
    assert again == disabled and again.expires_at_ms == first.expires_at_ms
    assert not again.enabled and again.activated_at_ms == BASE
    reject(
        "license_conflict",
        lambda: w["a"].issue_license(
            w["runtime"], license_id=w["id"], key=synthetic_key(), duration_seconds=60
        ),
    )
    reject(
        "license_conflict",
        lambda: w["a"].issue_license(
            w["runtime"], license_id=w["id"], key=w["key"], duration_seconds=61
        ),
    )
    reject(
        "license_conflict",
        lambda: w["a"].issue_license(
            w["runtime"], license_id=uuid4(), key=w["key"], duration_seconds=60
        ),
    )
    assert state(w) == disabled


def test_simultaneous_issue_and_activation_are_atomic(license_world):
    w = license_world
    key, license_id, barrier = synthetic_key(), uuid4(), Barrier(2)

    def issue():
        barrier.wait(3)
        return w["a"].issue_license(
            w["runtime"], license_id=license_id, key=key, duration_seconds=17
        )

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(issue) for _ in range(2)]
        assert futures[0].result() == futures[1].result()
    barrier = Barrier(2)

    def activate(device):
        barrier.wait(3)
        try:
            return run(w, request(w, device=device))
        except core.LicenseError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(activate, d) for d in (DEVICE, OTHER)]
        result = [f.result() for f in futures]
    assert result.count("device_mismatch") == 1
    winner = next(value for value in result if type(value) is core.LaunchGrant)
    assert state(w).device_id == winner.device_id and state(w).expires_at_ms == BASE + 60000
    with w["engine"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM aira_licenses")) == 2


def test_check_does_not_activate_and_retries_keep_fixed_expiry(license_world):
    w = license_world
    reject("not_activated", lambda: run(w, request(w, operation="check")))
    assert state(w).device_id is None
    first = run(w)
    w["clock"][0] += 20000
    second = run(w, request(w, nonce="d" * 64))
    checked = run(w, request(w, operation="check", nonce="e" * 64))
    assert first.expires_at_ms == second.expires_at_ms == checked.expires_at_ms == BASE + 60000
    assert second.checked_at_ms == checked.checked_at_ms == BASE + 20000
    assert second.nonce == "d" * 64 and checked.nonce == "e" * 64
    w["clock"][0] = BASE + 60000
    reject("license_expired", lambda: run(w))
    reject("license_expired", lambda: run(w, request(w, operation="check")))
    assert state(w).activated_at_ms == BASE


def test_disabled_unknown_clock_and_wrong_device_fail_closed(license_world):
    w = license_world
    reject("invalid_license", lambda: run(w, replace(request(w), license_key=synthetic_key())))
    reject(
        "invalid_license",
        lambda: run(w, replace(request(w, operation="check"), license_id=uuid4())),
    )
    w["clock"][0] = BASE - 1
    reject("clock_unavailable", lambda: run(w))
    w["clock"][0] = BASE
    run(w)
    reject("device_mismatch", lambda: run(w, request(w, operation="check", device=OTHER)))
    w["a"].set_enabled(w["runtime"], license_id=w["id"], enabled=False)
    reject("license_disabled", lambda: run(w))
    w["a"].set_enabled(w["runtime"], license_id=w["id"], enabled=True)
    assert run(w).expires_at_ms == BASE + 60000
    reject(
        "validation_error", lambda: w["a"].set_enabled(w["runtime"], license_id=w["id"], enabled=1)
    )


@pytest.mark.parametrize("committed", [False, True])
def test_uncertain_commit_retry_does_not_renew(license_world, monkeypatch, committed):
    w = license_world
    original = w["engine"].dialect.do_commit

    def broken(connection):
        if committed:
            original(connection)
        raise OSError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(w["engine"].dialect, "do_commit", broken)
        reject("license_storage_unavailable", lambda: run(w))
    before = state(w)
    assert (before.device_id is not None) is committed
    w["clock"][0] += 10000
    response = run(w)
    assert response.activated_at_ms == (BASE if committed else BASE + 10000)
    assert response.expires_at_ms == response.activated_at_ms + 60000


def test_schema_mismatch_does_not_trigger_runtime_migration(license_world):
    w = license_world
    with w["engine"].begin() as conn:
        conn.execute(text("UPDATE aira_license_schema SET revision=2"))
    reject("license_schema_unavailable", lambda: run(w))
    reject("license_schema_unavailable", lambda: w["a"].initialize_database(w["engine"]))
    with w["engine"].connect() as conn:
        assert conn.scalar(text("SELECT revision FROM aira_license_schema")) == 2
        assert conn.scalar(text("SELECT activated_at_ms FROM aira_licenses")) is None


def test_real_database_clock_is_used_when_not_injected(empty_pg_engine):
    a = api()
    a.initialize_database(empty_pg_engine)
    runtime = a.ServerRuntime(empty_pg_engine, secrets.token_bytes(32))
    key, identity = synthetic_key(), uuid4()
    a.issue_license(runtime, license_id=identity, key=key, duration_seconds=60)
    grant = core.decode_grant(
        a.process_request(runtime, core.StartRequest("activate", DEVICE, NONCE, license_key=key))
    )
    with empty_pg_engine.connect() as conn:
        now = conn.scalar(text("SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint"))
    assert 0 <= now - grant.checked_at_ms < 10000
    assert grant.expires_at_ms == grant.activated_at_ms + 60000


def test_http_activation_restart_check_and_no_admin_routes(license_world):
    w = license_world
    application = app(w)
    with TestClient(application, base_url="https://license.test") as client:
        activated = post(client, request(w))
        assert activated.status_code == 200 and activated.headers["cache-control"] == "no-store"
        first = core.decode_grant(activated.content)
        assert first.license_id == w["id"] and w["key"] not in activated.text
        assert client.get("/openapi.json").status_code == 404
        assert client.post("/license/v1/issue").status_code == 404
    w["clock"][0] += 10000
    with TestClient(app(w), base_url="https://license.test") as client:
        checked = post(client, request(w, operation="check", nonce="d" * 64))
        assert checked.status_code == 200
        second = core.decode_grant(checked.content)
        assert (
            second.expires_at_ms == first.expires_at_ms
            and second.checked_at_ms > first.checked_at_ms
        )
    assert set(application.openapi()["paths"]) == {"/license/v1/activate", "/license/v1/check"}
    for spec in application.openapi()["paths"].values():
        assert "requestBody" in spec["post"] and "200" in spec["post"]["responses"]


@pytest.mark.parametrize(
    "fault,status",
    [
        ("query", 422),
        ("media", 415),
        ("large", 413),
        ("extra", 422),
        ("duplicate", 422),
        ("route", 422),
        ("http", 400),
    ],
)
def test_http_rejections_are_safe_and_never_activate(license_world, fault, status):
    w = license_world
    headers = {"Content-Type": "application/json"}
    body = core.encode_request(request(w))
    path = "/license/v1/activate"
    if fault == "query":
        path += "?key=SYNTHETIC_PRIVATE"
    elif fault == "media":
        headers["Content-Type"] = "text/plain"
    elif fault == "large":
        body = b"x" * 8193
    elif fault in ("extra", "duplicate"):
        field = b'"secret"' if fault == "extra" else b'"nonce"'
        body = body[:-1] + b"," + field + b':"SYNTHETIC_PRIVATE"}'
    elif fault == "route":
        path = "/license/v1/check"
    base = "http://license.test" if fault == "http" else "https://license.test"
    with TestClient(app(w), base_url=base) as client:
        response = client.post(path, content=body, headers=headers)
    assert response.status_code == status and response.headers["cache-control"] == "no-store"
    assert "SYNTHETIC_PRIVATE" not in response.text and w["key"] not in response.text
    assert state(w).device_id is None


def test_four_requests_bound_sql_admission(license_world, monkeypatch):
    w = license_world
    module = importlib.import_module("ara.licensing.server._http")
    original = module.process_request
    entered, release, lock = [Event() for _ in range(4)], Event(), Lock()

    def blocked(*args):
        with lock:
            for event in entered:
                if not event.is_set():
                    event.set()
                    break
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(module, "process_request", blocked)
    with (
        TestClient(app(w), base_url="https://license.test") as client,
        ThreadPoolExecutor(4) as pool,
    ):
        try:
            futures = [pool.submit(post, client, request(w)) for _ in range(4)]
            assert all(event.wait(3) for event in entered)
            response = post(client, request(w))
            assert response.status_code == 503 and response.json()["code"] == "license_busy"
        finally:
            release.set()
        assert all(f.result().status_code == 200 for f in futures)


def test_body_timeout_precedes_storage_and_releases_admission(license_world, monkeypatch):
    w = license_world
    module = importlib.import_module("ara.licensing.server._http")
    monkeypatch.setattr(module, "BODY_TIMEOUT", 0.02)

    async def scenario():
        async def slow():
            yield b"{"
            await asyncio.sleep(0.2)
            yield b"}"

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(w)), base_url="https://license.test"
        ) as client:
            for _ in range(4):
                response = await client.post(
                    "/license/v1/activate",
                    content=slow(),
                    headers={"Content-Type": "application/json"},
                )
                assert (
                    response.status_code == 408 and response.headers["cache-control"] == "no-store"
                )
            assert state(w).device_id is None
            response = await client.post(
                "/license/v1/activate",
                content=core.encode_request(request(w)),
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 200

    asyncio.run(scenario())
    assert state(w).device_id == DEVICE


def test_safe_errors_do_not_reveal_connection_or_secret_values(license_world):
    w = license_world
    runtime = replace(w["runtime"], clock_ms=lambda: "SYNTHETIC_PRIVATE")
    with TestClient(w["a"].create_license_app(runtime), base_url="https://license.test") as client:
        response = post(client, request(w))
        assert response.status_code == 503
        assert "SYNTHETIC_PRIVATE" not in response.text and w["key"] not in response.text
    assert state(w).device_id is None
    assert w["runtime"].pepper.hex() not in repr(w["runtime"])


def test_other_schema_cannot_shadow_disabled_license(license_world):
    w = license_world
    run(w)
    w["a"].set_enabled(w["runtime"], license_id=w["id"], enabled=False)
    with w["engine"].begin() as conn:
        conn.execute(text("CREATE SCHEMA shadow"))
        for table in ("aira_license_schema", "aira_licenses"):
            conn.execute(text(f"CREATE TABLE shadow.{table} AS SELECT * FROM public.{table}"))
        conn.execute(text("UPDATE shadow.aira_licenses SET enabled=true"))

    def change_search_path(connection, record):
        with connection.cursor() as cursor:
            cursor.execute("SET search_path=shadow,public")
        connection.commit()

    event.listen(w["engine"], "connect", change_search_path)
    try:
        reject("license_disabled", lambda: run(w, request(w, operation="check")))
        assert state(w).enabled is False
    finally:
        event.remove(w["engine"], "connect", change_search_path)
