"""Operator panel acceptance with disposable PostgreSQL and synthetic credentials."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, inspect, select
from test_licensing_policy import DEVICE, synthetic_key
from test_licensing_server import license_world  # noqa: F401

from ara import licensing as core
from ara.license_admin.http import COOKIE, create_app
from ara.license_admin.security import AdminError, Settings, password_hash
from ara.license_admin.service import Service, attempts, audit, initialize, notes, sessions
from ara.licensing.server import ServerError
from ara.licensing.server._schema import licenses

ORIGIN = "https://admin.example.test"
PASSWORD = "SYNTHETIC-operator-password-123456"


@pytest.fixture(scope="module")
def settings():
    return Settings(ORIGIN, "admin", password_hash(PASSWORD), secrets.token_bytes(32))


@pytest.fixture
def panel(request, settings):
    w = request.getfixturevalue("license_world")
    initialize(w["engine"])
    service = Service(w["runtime"], settings)
    return w, service


def sign_in(service, remote="192.0.2.1"):
    return service.login("admin", PASSWORD, remote)


def issue(service, token, **changes):
    value = dict(identifier=str(uuid4()), key=synthetic_key(), days=30, label="Synthetic pilot")
    value.update(changes)
    return value, service.issue(token, **value)


def test_issuance_retry_activation_disable_and_secrets_are_not_stored(panel):
    w, s = panel
    token = sign_in(s)
    value, first = issue(s, token)
    assert first["status"] == "unactivated" and first["expires_at_ms"] is None
    grant = core.decode_grant(
        w["a"].process_request(
            w["runtime"],
            core.StartRequest("activate", DEVICE, secrets.token_hex(32), license_key=value["key"]),
        )
    )
    w["clock"][0] += 1000
    replay = s.issue(token, **value)
    assert replay["status"] == "active" and replay["expires_at_ms"] == grant.expires_at_ms
    assert replay["expires_at_ms"] - replay["activated_at_ms"] == 30 * 86400000
    s.disable(token, first["id"])
    assert s.issue(token, **value)["status"] == "disabled"
    with pytest.raises(core.LicenseError, match="disabled"):
        core.check(
            w["a"].get_license(w["runtime"], license_id=UUID(first["id"])),
            device_id=DEVICE,
            now_ms=w["clock"][0],
        )
    initialize(w["engine"])
    with w["engine"].connect() as c:
        assert (
            c.scalar(select(func.count()).select_from(audit).where(audit.c.action == "issue")) == 1
        )
        assert value["key"] not in repr(c.execute(select(licenses)).all())
        assert token not in repr(c.execute(select(sessions)).all())
        assert value["key"] not in repr(s.state(token)) and PASSWORD not in repr(s.settings)
    assert set(inspect(w["engine"]).get_table_names()) == {"aira_license_schema", "aira_licenses"}


def test_sessions_logout_expiry_restart_and_password_rotation(panel):
    w, s = panel
    token = sign_in(s)
    assert Service(w["runtime"], s.settings).state(token)["actor"] == "admin"
    changed = Service(
        w["runtime"], replace(s.settings, password=password_hash(PASSWORD + "changed"))
    )
    with pytest.raises(AdminError) as caught:
        changed.state(token)
    assert caught.value.status == 401
    s.logout(token)
    with pytest.raises(AdminError):
        s.state(token)
    token = sign_in(s)
    w["clock"][0] += 4 * 60 * 60 * 1000
    with pytest.raises(AdminError):
        s.state(token)


def test_login_rate_limit_survives_new_service_and_resets(panel):
    w, s = panel
    for _ in range(10):
        with pytest.raises(AdminError) as caught:
            s.login("admin", "wrong", "192.0.2.2")
        assert caught.value.status == 401
    with pytest.raises(AdminError) as caught:
        Service(w["runtime"], s.settings).login("admin", PASSWORD, "192.0.2.2")
    assert caught.value.status == 429
    w["clock"][0] += 15 * 60 * 1000
    assert s.state(sign_in(s, "192.0.2.2"))["actor"] == "admin"


def test_concurrent_retry_creates_one_record_and_preserves_disabled(panel):
    w, s = panel
    tokens = [sign_in(s), sign_in(s)]
    value = dict(identifier=str(uuid4()), key=synthetic_key(), days=7, label="Concurrent pilot")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda token: s.issue(token, **value), tokens))
    assert results[0] == results[1]
    s.disable(tokens[0], value["identifier"])
    assert s.issue(tokens[1], **value)["status"] == "disabled"
    with w["engine"].connect() as c:
        assert len(c.execute(select(notes)).all()) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"days": True},
        {"days": 0},
        {"days": "30"},
        {"days": 36501},
        {"label": ""},
        {"label": "x\ny"},
        {"identifier": str(UUID(int=0))},
        {"key": "weak"},
    ],
)
def test_invalid_issuance_does_not_add_licenses(panel, changes):
    w, s = panel
    token = sign_in(s)
    with pytest.raises((AdminError, core.LicenseError)):
        issue(s, token, **changes)
    with w["engine"].connect() as c:
        assert len(c.execute(select(licenses)).all()) == 1


def test_conflict_and_failed_audit_roll_back_all_changes(panel):
    w, s = panel
    token = sign_in(s)
    value, _ = issue(s, token)
    for changes in [{"key": synthetic_key()}, {"days": 29}, {"label": "different"}]:
        with pytest.raises(AdminError) as caught:
            s.issue(token, **(value | changes))
        assert caught.value.status == 409

    def fail_audit(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO aira_license_admin.audit"):
            raise OSError("SYNTHETIC failure")

    event.listen(w["engine"], "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(ServerError):
            issue(s, token)
    finally:
        event.remove(w["engine"], "before_cursor_execute", fail_audit)
    with w["engine"].connect() as c:
        assert len(c.execute(select(licenses)).all()) == 2
        assert len(c.execute(select(notes)).all()) == 1


def test_http_auth_csrf_origin_cookie_and_logout(panel):
    _, s = panel
    h = {"Origin": ORIGIN, "X-AIRA-Admin-Request": "1"}
    with TestClient(create_app(s), base_url=ORIGIN) as client:
        assert client.get("/license-admin/api/state", headers=h).status_code == 401
        assert (
            client.post(
                "/license-admin/api/login", json={"username": "admin", "password": PASSWORD}
            ).status_code
            == 403
        )
        login = client.post(
            "/license-admin/api/login", json={"username": "admin", "password": PASSWORD}, headers=h
        )
        assert login.status_code == 200
        cookie = login.headers["set-cookie"]
        assert all(v in cookie for v in ["Secure", "HttpOnly", "SameSite=strict", "Path=/"])
        state = client.get("/license-admin/api/state", headers=h)
        assert state.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in state.headers["content-security-policy"]
        value = dict(identifier=str(uuid4()), key=synthetic_key(), days=7, label="HTTP synthetic")
        assert client.post("/license-admin/api/issue", json=value, headers=h).status_code == 403
        write = h | {"X-AIRA-Admin-CSRF": state.json()["csrf"]}
        assert (
            client.post(
                "/license-admin/api/issue",
                json=value,
                headers=write | {"Origin": "https://other.example.test"},
            ).status_code
            == 403
        )
        issued = client.post("/license-admin/api/issue", json=value, headers=write)
        assert issued.status_code == 200 and value["key"] not in issued.text
        assert (
            client.post(
                "/license-admin/api/disable",
                json={"identifier": issued.json()["id"]},
                headers=write,
            ).status_code
            == 200
        )
        assert client.post("/license-admin/api/logout", json={}, headers=write).status_code == 200
        assert client.get("/license-admin/api/state", headers=h).status_code == 401
        assert COOKIE not in client.cookies


def test_http_size_duplicates_tls_and_no_extra_endpoints(panel):
    _, s = panel
    h = {"Origin": ORIGIN, "X-AIRA-Admin-Request": "1", "Content-Type": "application/json"}
    with TestClient(create_app(s), base_url=ORIGIN) as c:
        assert c.post("/license-admin/api/login", content="x" * 4097, headers=h).status_code == 413
        assert (
            c.post(
                "/license-admin/api/login", content='{"username":"a","username":"b"}', headers=h
            ).status_code
            == 422
        )
        assert c.get("/license-admin/api/password", headers=h).status_code == 404
        assert c.get("/docs").status_code == 404
    with TestClient(create_app(s), base_url=ORIGIN.replace("https:", "http:")) as c:
        assert c.get("/license-admin/").status_code == 400


def test_pagination_existing_licenses_and_expiry(panel):
    w, s = panel
    token = sign_in(s)
    for number in range(51):
        issue(s, token, label=f"Synthetic {number}")
    first, second = s.state(token), s.state(token, offset=50)
    assert len(first["licenses"]) == 50 and first["more"]
    assert len(second["licenses"]) == 2 and not second["more"]
    assert not ({r["id"] for r in first["licenses"]} & {r["id"] for r in second["licenses"]})
    value, _ = issue(s, token, days=1)
    w["a"].process_request(
        w["runtime"],
        core.StartRequest("activate", DEVICE, secrets.token_hex(32), license_key=value["key"]),
    )
    w["clock"][0] += 86400000
    token = sign_in(s)
    row = next(r for r in s.state(token)["licenses"] if r["id"] == value["identifier"])
    assert row["status"] == "expired"


def test_global_rate_limit_bounds_source_buckets(panel):
    w, s = panel
    with w["engine"].begin() as connection:
        connection.execute(
            attempts.insert().values(bucket="global", window=w["clock"][0] // 900000, count=100)
        )
    for source in ["192.0.2.10", "192.0.2.11"]:
        with pytest.raises(AdminError) as caught:
            sign_in(s, source)
        assert caught.value.status == 429
    with w["engine"].connect() as connection:
        assert connection.scalar(select(func.count()).select_from(attempts)) == 1


def test_public_assets_have_explicit_types_and_no_inline_scripts(panel):
    _, s = panel
    with TestClient(create_app(s), base_url=ORIGIN) as client:
        page = client.get("/license-admin/")
        assert page.status_code == 200 and '<script src="./admin.js" defer>' in page.text
        assert "unsafe-inline" not in page.headers["content-security-policy"]
        assert (
            client.get("/license-admin/admin.js")
            .headers["content-type"]
            .startswith("text/javascript")
        )
        assert client.get("/license-admin/admin.css").headers["content-type"].startswith("text/css")
        assert client.get("/license-admin/../../secrets.env").status_code == 404
