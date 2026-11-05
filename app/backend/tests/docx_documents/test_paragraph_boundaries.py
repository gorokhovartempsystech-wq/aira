"""Stream limits, strict bigint/schema bounds and inert paragraph modules."""

import asyncio
import importlib
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from ara.app import create_app
from ara.documents.runtime import DocumentRuntime
from ara.docx_documents.paragraph_schemas import ParagraphCommandsRequest
from ara.docx_package.creation import create_docx
from ara.docx_package.projection import project_docx

ROOT = Path(__file__).resolve().parents[2]
MAX = 9223372036854775807


def sample():
    p = project_docx(create_docx()).blocks[0]
    anchor = asdict(p.anchor)
    anchor["path"] = list(anchor["path"])
    return {
        "expected_storage_revision": "1",
        "kind": "format",
        "commands": [{"kind": "format", "anchor": anchor, "expected_text": ""}],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("style_id", "a\t"),
        ("style_id", "a\r"),
        ("style_id", "a\ud800"),
        ("list_id", "2147483648"),
        ("list_id", "0"),
        ("list_id", "01"),
        ("list_kind", "ordered"),
    ],
)
def test_native_format_validation_does_not_coerce_values(field, value):
    body = sample()
    body["commands"][0][field] = value
    with pytest.raises(ValidationError):
        ParagraphCommandsRequest.model_validate(body)


def test_bigint_bound_and_schema_reference_discriminator():
    body = sample()
    body["expected_storage_revision"] = str(MAX - 1)
    assert ParagraphCommandsRequest.model_validate(body).expected_storage_revision == str(MAX - 1)
    for value in (str(MAX), "01", "1\n", 1, True):
        body["expected_storage_revision"] = value
        with pytest.raises(ValidationError):
            ParagraphCommandsRequest.model_validate(body)
    schema = ParagraphCommandsRequest.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["commands"]["items"]["discriminator"]["propertyName"] == "kind"


@pytest.mark.parametrize(
    "kind",
    [
        "declared",
        "streamed",
        "disconnect",
        "duplicate_type",
        "duplicate_length",
        "duplicate_encoding",
        "length_mismatch",
        "length_transfer",
    ],
)
def test_stream_rejected_before_storage_and_drain_stops(monkeypatch, kind):
    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected storage access")

    engine = create_engine("postgresql+psycopg://")
    monkeypatch.setattr(engine, "connect", forbidden)
    monkeypatch.setattr(
        importlib.import_module("ara.docx_documents.paragraph_storage"), "save_commands", forbidden
    )
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
    app = create_app(document_runtime=runtime)
    headers = [(b"content-type", b"application/json"), (b"idempotency-key", str(uuid4()).encode())]
    chunks = [{"type": "http.request", "body": b"{}", "more_body": False}]
    expected_reads, status, code = 0, 422, "validation_error"
    if kind == "declared":
        headers.append((b"content-length", b"2097153"))
        status, code = 413, "edit_request_too_large"
    elif kind == "streamed":
        chunks = [
            {"type": "http.request", "body": b"x" * 2097152, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": True},
            {"type": "http.request", "body": b"unread", "more_body": False},
        ]
        expected_reads, status, code = 2, 413, "edit_request_too_large"
    elif kind == "disconnect":
        chunks, expected_reads = [{"type": "http.disconnect"}], 1
    elif kind == "duplicate_type":
        headers.append((b"content-type", b"application/json"))
    elif kind == "duplicate_length":
        headers.extend([(b"content-length", b"2"), (b"content-length", b"2")])
    elif kind == "duplicate_encoding":
        headers.extend([(b"content-encoding", b"identity"), (b"content-encoding", b"identity")])
    elif kind == "length_mismatch":
        headers.append((b"content-length", b"3"))
        expected_reads = 1
    else:
        headers.extend([(b"content-length", b"2"), (b"transfer-encoding", b"chunked")])

    async def run():
        sent, received = [], []
        iterator = iter(chunks)

        async def receive():
            message = next(iterator, None)
            if message is None:
                await asyncio.Event().wait()
            received.append(message)
            return message

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "root_path": "",
            "path": f"/docx-documents/{uuid4()}/paragraph-commands",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1),
            "server": ("localhost", 80),
        }
        await asyncio.wait_for(app(scope, receive, send), 5)
        return received, sent

    try:
        received, sent = asyncio.run(run())
    finally:
        engine.dispose()
    assert len(received) == expected_reads
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == status
    assert (b"cache-control", b"no-store") in start["headers"]
    response = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert json.loads(response)["code"] == code


def test_paragraph_module_imports_do_not_read_secrets_open_network_or_log():
    script = """
import builtins,io,os,socket,subprocess,importlib,logging
from pathlib import Path
import sqlalchemy,psycopg,pydantic
def forbidden(*args,**kwargs):raise AssertionError('Unexpected external I/O')
for obj,name in ((builtins,'open'),(io,'open'),(Path,'read_bytes'),(Path,'read_text'),
                 (os,'getenv'),(socket,'socket'),(subprocess,'Popen'),
                 (psycopg,'connect'),(sqlalchemy,'create_engine'),(logging.Logger,'_log')):
    setattr(obj,name,forbidden)
for name in ('paragraph_schemas','paragraph_storage','paragraph_http'):
    importlib.import_module('ara.docx_documents.'+name)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout
