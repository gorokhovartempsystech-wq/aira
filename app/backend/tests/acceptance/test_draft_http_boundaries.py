"""Independent wire validation and OpenAPI checks without storage access."""

import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ara.app import create_app
from ara.documents.runtime import DocumentRuntime

PRIVATE = "SYNTHETIC_PRIVATE_HTTP_DRAFT_732"
MAX_EXPECTED = 9223372036854775806
PATH = "/documents/{document_id}/draft"
SNAPSHOT_FIELDS = {"document_id", "base_version_id", "revision", "content_markdown", "updated_at"}
ERROR_FIELDS = {"code", "message", "retryable", "request_id"}


@pytest.fixture
def disconnected_client(monkeypatch):
    engine = create_engine("postgresql+psycopg://synthetic@localhost/unused")

    def forbidden(*args, **kwargs):
        pytest.fail("Draft request validation or app metadata opened/disposed storage")

    with monkeypatch.context() as patch:
        patch.delenv("ARA_ENVIRONMENT", raising=False)
        patch.setattr(engine, "connect", forbidden)
        patch.setattr(engine, "dispose", forbidden)
        runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
        with TestClient(create_app(document_runtime=runtime)) as client:
            yield client
    engine.dispose()


def body():
    return {"expected_revision": 0, "base_version_id": str(uuid4()), "content_markdown": PRIVATE}


def put(client, value, *, path=None):
    return client.put(
        path or PATH.format(document_id=uuid4()),
        content=json.dumps(value, ensure_ascii=True),
        headers={"Content-Type": "application/json", "X-Request-ID": PRIVATE},
    )


def invalid(response, seen):
    assert response.status_code == 422
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    result = response.json()
    assert set(result) == ERROR_FIELDS
    assert (result["code"], result["message"], result["retryable"]) == (
        "validation_error",
        "Invalid request",
        False,
    )
    assert PRIVATE not in response.text
    assert str(UUID(result["request_id"])) == result["request_id"]
    assert result["request_id"] not in seen
    seen.add(result["request_id"])


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("expected_revision", [-1, MAX_EXPECTED + 1, 0.0, True, "0", None, [], {}]),
        ("base_version_id", [None, True, 42, [], {}, PRIVATE, ""]),
        ("content_markdown", [None, True, 42, [], {}, PRIVATE + "\x00", PRIVATE + "\ud800"]),
    ],
)
def test_invalid_field_values_fail_before_storage(disconnected_client, field, values):
    seen = set()
    for value in values:
        invalid(put(disconnected_client, {**body(), field: value}), seen)


def test_missing_and_extra_fields_fail_before_storage(disconnected_client):
    seen = set()
    for field in body():
        value = body()
        del value[field]
        invalid(put(disconnected_client, value), seen)
    for field in ("document_id", "user_id", "project_id", "revision", "updated_at"):
        invalid(put(disconnected_client, {**body(), field: PRIVATE}), seen)


def test_nonobject_and_absent_bodies_fail_before_storage(disconnected_client):
    seen = set()
    for value in (None, [], PRIVATE, 1, True, {}):
        invalid(put(disconnected_client, value), seen)
    invalid(disconnected_client.put(PATH.format(document_id=uuid4())), seen)


def test_malformed_json_and_utf8_have_safe_unique_errors(disconnected_client):
    seen = set()
    for raw in (b'{"content_markdown":"' + PRIVATE.encode(), b'{"x":"\xff"}', b"{bad json}"):
        for _ in range(2):
            invalid(
                disconnected_client.put(
                    PATH.format(document_id=uuid4()),
                    content=raw,
                    headers={"Content-Type": "application/json", "X-Request-ID": PRIVATE},
                ),
                seen,
            )


def test_invalid_path_uuid_fails_before_storage(disconnected_client):
    seen = set()
    for value in (PRIVATE, "123", "null"):
        path = PATH.format(document_id=value)
        invalid(disconnected_client.get(path), seen)
        invalid(put(disconnected_client, body(), path=path), seen)


def resolve(openapi, value):
    while "$ref" in value:
        target = openapi
        for part in value["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        value = target
    return value


def response_schema(openapi, method, status):
    response = openapi["paths"][PATH][method]["responses"][str(status)]
    return resolve(openapi, response["content"]["application/json"]["schema"])


def assert_snapshot(schema):
    assert schema["type"] == "object"
    assert set(schema["properties"]) == set(schema["required"]) == SNAPSHOT_FIELDS
    assert schema["additionalProperties"] is False
    for field in ("document_id", "base_version_id"):
        assert schema["properties"][field]["type"] == "string"
        assert schema["properties"][field]["format"] == "uuid"
    assert schema["properties"]["revision"]["type"] == "integer"
    assert schema["properties"]["content_markdown"]["type"] == "string"
    assert schema["properties"]["updated_at"]["format"] == "date-time"


def test_openapi_describes_draft_wire_contract_without_storage(disconnected_client):
    assert disconnected_client.get("/health").json() == {"status": "ok"}
    response = disconnected_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert set(schema["paths"][PATH]) == {"get", "put"}
    request = schema["paths"][PATH]["put"]["requestBody"]
    assert request["required"] is True
    request_schema = resolve(schema, request["content"]["application/json"]["schema"])
    assert set(request_schema["properties"]) == set(request_schema["required"]) == set(body())
    assert request_schema["additionalProperties"] is False
    fields = request_schema["properties"]
    assert fields["expected_revision"]["type"] == "integer"
    assert fields["expected_revision"]["minimum"] == 0
    assert (
        fields["expected_revision"].get("maximum") == MAX_EXPECTED
        or fields["expected_revision"].get("exclusiveMaximum") == MAX_EXPECTED + 1
    )
    assert fields["base_version_id"]["type"] == "string"
    assert fields["base_version_id"]["format"] == "uuid"
    assert fields["content_markdown"]["type"] == "string"
    assert "maxLength" not in fields["content_markdown"]
    assert fields["content_markdown"].get("minLength", 0) == 0
    assert_snapshot(response_schema(schema, "put", 200))
    nullable = response_schema(schema, "get", 200)
    alternatives = [
        resolve(schema, item) for item in nullable.get("anyOf", nullable.get("oneOf", []))
    ]
    assert len(alternatives) == 2
    assert {item.get("type") for item in alternatives} == {"object", "null"}
    assert_snapshot(next(item for item in alternatives if item.get("type") == "object"))
    for method in ("get", "put"):
        parameter = next(
            item for item in schema["paths"][PATH][method]["parameters"] if item["in"] == "path"
        )
        assert parameter["name"] == "document_id" and parameter["required"] is True
        assert parameter["schema"]["type"] == "string"
        assert parameter["schema"]["format"] == "uuid"
        for status in (404, 422, 500, 503) if method == "get" else (404, 409, 422, 500, 503):
            error = response_schema(schema, method, status)
            assert error["type"] == "object"
            assert set(error["properties"]) == set(error["required"]) == ERROR_FIELDS
            assert error["properties"]["code"]["type"] == "string"
            assert error["properties"]["message"]["type"] == "string"
            assert error["properties"]["retryable"]["type"] == "boolean"
            assert error["properties"]["request_id"]["type"] == "string"


def test_health_only_app_does_not_install_draft_routes():
    with TestClient(create_app()) as client:
        assert set(client.get("/openapi.json").json()["paths"]) == {"/health"}
        path = PATH.format(document_id=uuid4())
        assert client.get(path).status_code == 404
        assert client.put(path, json=body()).status_code == 404
