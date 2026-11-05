"""The HTTP boundary delegates unchanged values to the public draft service."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import ara.drafts
from ara.app import create_app
from ara.documents.runtime import DocumentRuntime

MAX_EXPECTED = 9223372036854775806
SAVED_AT = datetime(2026, 10, 28, 12, 34, 56, 123456, timezone(timedelta(hours=5, minutes=45)))


@pytest.fixture
def transport(monkeypatch):
    engine = create_engine("postgresql+psycopg://synthetic@localhost/unused")
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
    read = Mock(return_value=None)

    def saved_snapshot(runtime, **values):
        return ara.drafts.DraftSnapshot(
            document_id=values["document_id"],
            base_version_id=values["base_version_id"],
            revision=values["expected_revision"] + 1,
            content_markdown=values["content_markdown"],
            updated_at=SAVED_AT,
        )

    save = Mock(side_effect=saved_snapshot)

    def forbidden(*args, **kwargs):
        pytest.fail("The transport must delegate storage exclusively to the draft service")

    with monkeypatch.context() as patch:
        patch.delenv("ARA_ENVIRONMENT", raising=False)
        patch.setattr(engine, "connect", forbidden)
        patch.setattr(engine, "dispose", forbidden)
        patch.setattr(ara.drafts, "read_draft", read)
        patch.setattr(ara.drafts, "save_draft", save)
        with TestClient(create_app(document_runtime=runtime)) as client:
            yield SimpleNamespace(client=client, runtime=runtime, read=read, save=save)
    engine.dispose()


@pytest.mark.parametrize("form", ["canonical", "uppercase", "hex", "braces", "urn"])
def test_python_uuid_strings_become_uuid_objects_and_canonical_responses(transport, form):
    document_id, base_version_id = uuid4(), uuid4()

    def render(value):
        return {
            "canonical": str(value),
            "uppercase": str(value).upper(),
            "hex": value.hex,
            "braces": "{" + str(value) + "}",
            "urn": value.urn,
        }[form]

    path = f"/documents/{render(document_id)}/draft"
    response = transport.client.put(
        path,
        json={
            "expected_revision": 0,
            "base_version_id": render(base_version_id),
            "content_markdown": "Synthetic text",
        },
    )
    assert response.status_code == 200
    transport.save.assert_called_once_with(
        transport.runtime,
        document_id=document_id,
        expected_revision=0,
        base_version_id=base_version_id,
        content_markdown="Synthetic text",
    )
    result = response.json()
    assert result["document_id"] == str(document_id)
    assert result["base_version_id"] == str(base_version_id)
    assert transport.client.get(path).json() is None
    transport.read.assert_called_once_with(transport.runtime, document_id=document_id)


@pytest.mark.parametrize("expected_revision", [0, MAX_EXPECTED])
@pytest.mark.parametrize(
    "content",
    ["", " \t\r\n# Незакрытая [ссылка\r\ne\u0301 🙂 \r\n", "я" * 1_000_001],
    ids=["empty", "exact-unicode-markdown", "over-million"],
)
def test_put_preserves_text_and_full_revision_range(transport, expected_revision, content):
    document_id, base_version_id = uuid4(), uuid4()
    response = transport.client.put(
        f"/documents/{document_id}/draft",
        json={
            "expected_revision": expected_revision,
            "base_version_id": str(base_version_id),
            "content_markdown": content,
        },
    )
    assert response.status_code == 200
    transport.save.assert_called_once_with(
        transport.runtime,
        document_id=document_id,
        expected_revision=expected_revision,
        base_version_id=base_version_id,
        content_markdown=content,
    )
    assert type(transport.save.call_args.kwargs["expected_revision"]) is int
    assert response.json() == {
        "document_id": str(document_id),
        "base_version_id": str(base_version_id),
        "revision": expected_revision + 1,
        "content_markdown": content,
        "updated_at": SAVED_AT.isoformat(),
    }
    transport.read.assert_not_called()


@pytest.mark.parametrize("has_draft", [False, True])
def test_get_returns_service_result_without_attempting_a_save(transport, has_draft):
    document_id = uuid4()
    snapshot = ara.drafts.DraftSnapshot(
        document_id=document_id,
        base_version_id=uuid4(),
        revision=7,
        content_markdown="  Synthetic snapshot\r\n",
        updated_at=SAVED_AT,
    )
    transport.read.return_value = snapshot if has_draft else None
    response = transport.client.get(f"/documents/{document_id}/draft")
    assert response.status_code == 200
    assert response.json() == (snapshot.model_dump(mode="json") if has_draft else None)
    transport.read.assert_called_once_with(transport.runtime, document_id=document_id)
    transport.save.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_identity_headers_and_query_cannot_replace_server_runtime(transport, method):
    document_id, base_version_id, foreign_id = uuid4(), uuid4(), str(uuid4())
    response = transport.client.request(
        method,
        f"/documents/{document_id}/draft",
        params={"user_id": foreign_id, "project_id": foreign_id, "document_id": foreign_id},
        headers={"X-User-ID": foreign_id, "X-Project-ID": foreign_id},
        **(
            {
                "json": {
                    "expected_revision": 0,
                    "base_version_id": str(base_version_id),
                    "content_markdown": "Synthetic ownership check",
                }
            }
            if method == "PUT"
            else {}
        ),
    )
    assert response.status_code == 200
    service = transport.save if method == "PUT" else transport.read
    assert service.call_count == 1
    assert service.call_args.args == (transport.runtime,)
    assert service.call_args.args[0] is transport.runtime
    assert service.call_args.kwargs["document_id"] == document_id
    assert not {"user_id", "project_id"}.intersection(service.call_args.kwargs)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"private":',
        b'{"private":"\xff"}',
        b"null",
        b'{"expected_revision":true,"base_version_id":"private","content_markdown":""}',
        b'{"expected_revision":0,"base_version_id":42,"content_markdown":"private"}',
        json.dumps(
            {
                "expected_revision": 0,
                "base_version_id": str(uuid4()),
                "content_markdown": "private",
                "user_id": "private",
            }
        ).encode(),
    ],
    ids=["json", "utf8", "null", "boolean-revision", "numeric-uuid", "extra-field"],
)
def test_malformed_input_never_reaches_either_service_function(transport, raw):
    response = transport.client.put(
        f"/documents/{uuid4()}/draft",
        content=raw,
        headers={"Content-Type": "application/json", "X-Request-ID": "private"},
    )
    assert response.status_code == 422
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    error = response.json()
    assert set(error) == {"code", "message", "retryable", "request_id"}
    assert (error["code"], error["message"], error["retryable"]) == (
        "validation_error",
        "Invalid request",
        False,
    )
    assert str(UUID(error["request_id"])) == error["request_id"]
    assert "private" not in response.text
    transport.read.assert_not_called()
    transport.save.assert_not_called()


@pytest.mark.parametrize(
    "encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"]
)
def test_json_in_other_encodings_is_rejected_before_service(transport, encoding):
    raw = json.dumps(
        {
            "expected_revision": 0,
            "base_version_id": str(uuid4()),
            "content_markdown": "private",
        }
    ).encode(encoding)
    response = transport.client.put(
        f"/documents/{uuid4()}/draft",
        content=raw,
        headers={"Content-Type": "application/json", "X-Request-ID": "private"},
    )
    assert response.status_code == 422
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    error = response.json()
    assert set(error) == {"code", "message", "retryable", "request_id"}
    assert (error["code"], error["message"], error["retryable"]) == (
        "validation_error",
        "Invalid request",
        False,
    )
    assert str(UUID(error["request_id"])) == error["request_id"]
    assert "private" not in response.text
    transport.read.assert_not_called()
    transport.save.assert_not_called()


def test_openapi_keeps_exact_integer_limits_and_metadata_never_invokes_service(transport):
    def resolve(schema, value):
        while "$ref" in value:
            target = schema
            for part in value["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            value = target
        return value

    for _ in range(3):
        assert transport.client.get("/health").json() == {"status": "ok"}
        response = transport.client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        put = schema["paths"]["/documents/{document_id}/draft"]["put"]
        request = resolve(schema, put["requestBody"]["content"]["application/json"]["schema"])
        snapshot = resolve(schema, put["responses"]["200"]["content"]["application/json"]["schema"])
        for actual, expected in (
            (request["properties"]["expected_revision"]["maximum"], MAX_EXPECTED),
            (snapshot["properties"]["revision"]["maximum"], MAX_EXPECTED + 1),
        ):
            assert type(actual) is int
            assert actual == expected
    transport.read.assert_not_called()
    transport.save.assert_not_called()
