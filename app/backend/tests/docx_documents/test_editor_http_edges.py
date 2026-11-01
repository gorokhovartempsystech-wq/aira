"""Raw ASGI framing, lost responses and middleware ownership boundaries."""

import asyncio
import importlib
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ara.app import create_app
from ara.documents.runtime import DocumentRuntime
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_editor_http import command, opened, path
from tests.acceptance.test_docx_text_edit import seed


def asgi_call(app, target, headers, chunks, *, fail_send=False):
    async def run():
        received, sent = [], []
        iterator = iter(chunks)

        async def receive():
            message = next(iterator, None)
            if message is None:
                await asyncio.Event().wait()
            received.append(message)
            return message

        async def send(message):
            sent.append(message)
            if fail_send and message["type"] == "http.response.body":
                raise RuntimeError("Synthetic lost response")

        scope = dict(
            type="http",
            asgi={"version": "3.0", "spec_version": "2.3"},
            http_version="1.1",
            method="POST",
            scheme="http",
            root_path="",
            path=target,
            query_string=b"",
            headers=headers,
            client=("127.0.0.1", 1),
            server=("localhost", 80),
        )
        await asyncio.wait_for(app(scope, receive, send), 10)
        return received, sent

    return asyncio.run(run())


@pytest.mark.parametrize(
    "kind",
    [
        "declared",
        "streamed",
        "disconnect",
        "duplicate_type",
        "duplicate_length",
        "duplicate_encoding",
        "duplicate_transfer",
        "length_mismatch",
        "length_transfer",
        "bad_transfer",
    ],
)
def test_invalid_stream_and_headers_stop_before_dispatch(monkeypatch, kind):
    engine = create_engine("postgresql+psycopg://")

    def forbidden(*args, **kwargs):
        raise AssertionError("Storage/runtime accessed")

    monkeypatch.setattr(engine, "connect", forbidden)
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
    app = create_app(document_runtime=runtime)
    monkeypatch.setattr(app.state.docx_editor_registry, "checkpoint", forbidden)
    headers = [(b"content-type", b"application/json")]
    chunks = [dict(type="http.request", body=b"{}", more_body=False)]
    reads, status, code = 0, 422, "validation_error"
    if kind == "declared":
        headers.append((b"content-length", b"65537"))
        status, code = 413, "editor_request_too_large"
    elif kind == "streamed":
        chunks = [
            dict(type="http.request", body=b"x" * 65536, more_body=True),
            dict(type="http.request", body=b"x", more_body=True),
            dict(type="http.request", body=b"unread", more_body=False),
        ]
        reads, status, code = 2, 413, "editor_request_too_large"
    elif kind == "disconnect":
        chunks, reads = [{"type": "http.disconnect"}], 1
    elif kind == "duplicate_type":
        headers.append((b"Content-Type", b"application/json"))
    elif kind == "duplicate_length":
        headers += [(b"content-length", b"2"), (b"content-length", b"2")]
    elif kind == "duplicate_encoding":
        headers += [(b"content-encoding", b"identity"), (b"content-encoding", b"identity")]
    elif kind == "duplicate_transfer":
        headers += [(b"transfer-encoding", b"chunked"), (b"transfer-encoding", b"chunked")]
    elif kind == "length_mismatch":
        headers.append((b"content-length", b"3"))
        reads = 1
    elif kind == "length_transfer":
        headers += [(b"content-length", b"2"), (b"transfer-encoding", b"chunked")]
    else:
        headers.append((b"transfer-encoding", b"unknown"))
    try:
        received, sent = asgi_call(
            app, f"/docx-documents/{uuid4()}/editor-sessions/{uuid4()}/checkpoint", headers, chunks
        )
    finally:
        engine.dispose()
    assert len(received) == reads
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == status and (b"cache-control", b"no-store") in start["headers"]
    result = json.loads(
        b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    )
    assert result["code"] == code


def test_chunked_command_is_accepted_and_lost_response_replays_once(run_world):
    item = seed(run_world)
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    with TestClient(app) as http:
        view, _ = opened(http, item)
        request = command(view, "insert_text", "Once ")
        body = json.dumps(request).encode()
        headers = [(b"content-type", b"application/json"), (b"transfer-encoding", b"chunked")]
        chunks = [
            dict(type="http.request", body=body[:20], more_body=True),
            dict(type="http.request", body=body[20:], more_body=False),
        ]
        with pytest.raises(Exception):
            asgi_call(app, path(item, view) + "/commands", headers, chunks, fail_send=True)
        assert http.get(path(item, view)).json()["command_sequence"] == "1"
        replay = http.post(path(item, view) + "/commands", json=request)
        assert replay.status_code == 200 and replay.json()["command_sequence"] == "1"
        full = http.get(path(item, view) + "/view").json()
        assert full["projection"]["blocks"][0]["text"].startswith("Once Device")
        assert "Once Once" not in full["projection"]["blocks"][0]["text"]


def test_worker_and_codec_failures_release_gate_and_hide_input(run_world, monkeypatch):
    item = seed(run_world)
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    with TestClient(app) as http:
        view, _ = opened(http, item)

        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_PRIVATE")

        with monkeypatch.context() as patch:
            patch.setattr(app.state.docx_editor_registry, "command", fail)
            response = http.post(
                path(item, view) + "/commands",
                json=command(view, "insert_text", "SYNTHETIC_PRIVATE"),
            )
            assert response.status_code == 500 and response.json()["code"] == "editor_error"
            assert "SYNTHETIC_PRIVATE" not in response.text
        assert http.get(path(item, view)).json()["command_sequence"] == "0"
        assert (
            http.post(
                path(item, view) + "/commands", json=command(view, "insert_text", "Next ")
            ).status_code
            == 200
        )
        assert http.get(path(item, view) + "/unknown").status_code == 404
        assert http.delete(path(item, view)).status_code == 405


def test_path_uuid_aliases_unknown_queries_and_content_coding_are_refused(run_world):
    item = seed(run_world)
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    with TestClient(app) as http:
        view, _ = opened(http, item)
        alias = path(item, view).replace(str(item.document_id), item.document_id.hex)
        assert http.get(alias).status_code == 422
        assert http.get(path(item, view) + "?&").status_code == 422
        assert http.get(path(item, view), headers={"Content-Encoding": "gzip"}).status_code == 415
        response = http.post(
            path(item, view) + "/commands",
            json=command(view, "insert_text", "X"),
            headers={"Content-Type": "Application/JSON; Charset=UTF-8"},
        )
        assert response.status_code == 200


def test_http_modules_and_health_only_construction_are_inert():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid,sys,copy,contextlib,functools
import hashlib,re,zipfile,xml.etree.ElementTree,typing,datetime,threading,inspect
from pathlib import Path
import sqlalchemy,psycopg,fastapi
from pydantic import TypeAdapter
TypeAdapter(str)  # Warm third-party plugin discovery before guarding the app.
from ara.app import create_app
assert 'ara.docx_editor.http' not in sys.modules
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
def framework_flag(name,default=None):
 assert name=='PYDANTIC_DISABLE_PLUGINS'
 return None
os.getenv=framework_flag
for obj,name in ((builtins,'open'),(io,'open'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes'),
                 (sqlalchemy,'create_engine'),(psycopg,'connect')):
 setattr(obj,name,forbidden)
app=create_app()
assert 'ara.docx_editor.http' not in sys.modules
import ara.docx_editor.http
assert not hasattr(app.state,'docx_editor_registry')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={"PYTHONPATH": str(Path.cwd() / "src")},
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout


def test_installation_is_explicit_and_cannot_duplicate_lifetime(run_world):
    from ara.config import ConfigurationError

    app = create_app(document_runtime=run_world["runtimes"]["own"])
    before = app.state.docx_editor_registry
    with pytest.raises(ConfigurationError):
        importlib.import_module("ara.docx_editor.http").install_editor_json(
            app, run_world["runtimes"]["own"]
        )
    assert app.state.docx_editor_registry is before


def test_cancelled_request_keeps_gate_until_worker_finishes(run_world, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import anyio

    item = seed(run_world)
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    entered, permit, cancelled = Event(), Event(), Event()
    with TestClient(app) as http:
        view, _ = opened(http, item)
        request = command(view, "insert_text", "Once ")
        real = app.state.docx_editor_registry.command

        def blocked(**kwargs):
            result = real(**kwargs)
            entered.set()
            assert permit.wait(5)
            return result

        monkeypatch.setattr(app.state.docx_editor_registry, "command", blocked)

        async def run():
            chunks = iter(
                [dict(type="http.request", body=json.dumps(request).encode(), more_body=False)]
            )

            async def receive():
                message = next(chunks, None)
                if message is None:
                    await anyio.sleep_forever()
                return message

            async def send(message):
                pass

            scope = dict(
                type="http",
                asgi={"version": "3.0", "spec_version": "2.3"},
                http_version="1.1",
                method="POST",
                scheme="http",
                root_path="",
                path=path(item, view) + "/commands",
                query_string=b"",
                headers=[(b"content-type", b"application/json")],
                client=("127.0.0.1", 1),
                server=("localhost", 80),
            )
            with anyio.CancelScope() as cancellation:
                async with anyio.create_task_group() as group:
                    group.start_soon(app, scope, receive, send)
                    assert await anyio.to_thread.run_sync(entered.wait, 5)
                    cancellation.cancel()
                    cancelled.set()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(anyio.run, run)
            assert cancelled.wait(5)
            try:
                busy = http.get(path(item, view))
                assert busy.status_code == 503 and busy.json()["code"] == "editor_busy"
            finally:
                permit.set()
            future.result(10)
        assert http.get(path(item, view)).json()["command_sequence"] == "1"
        assert (
            http.post(path(item, view) + "/commands", json=request).json()["command_sequence"]
            == "1"
        )
