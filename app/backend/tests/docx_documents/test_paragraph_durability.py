"""Independent process replay, shared keys and BIGINT end-of-range behavior."""

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from ara.app import create_app
from ara.docx_documents import get_docx, import_docx
from ara.docx_documents._dto import MAX_REVISION
from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.projection import project_docx
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.docx_documents.test_storage_edges import runtime as runtime


def prepare(runtime):
    item = import_docx(
        runtime,
        document_id=uuid4(),
        title="Synthetic",
        data=create_docx((NewParagraph("First"), NewParagraph("Second"))),
    )
    p = project_docx(item.current_data).blocks[0]
    anchor = asdict(p.anchor)
    anchor["path"] = list(anchor["path"])
    return item, {
        "expected_storage_revision": "1",
        "kind": "format",
        "commands": [
            {"kind": "format", "anchor": anchor, "expected_text": p.text, "style_id": "Heading1"}
        ],
    }


def test_new_process_replays_and_omitted_defaults_have_same_fingerprint(runtime):
    item, body = prepare(runtime)
    path = f"/docx-documents/{item.document_id}/paragraph-commands"
    key = str(uuid4())
    with TestClient(create_app(document_runtime=runtime)) as http:
        response = http.post(path, json=body, headers={"Idempotency-Key": key})
        assert response.status_code == 200, response.text
        expected = response.json()
    url = runtime.engine.url
    # All values describe a synthetic disposable database, without passwords.
    assert url.password is None and url.database.startswith("ara_check_")
    payload = {
        "user": str(runtime.user_id),
        "project": str(runtime.project_id),
        "username": url.username,
        "database": url.database,
        "host": url.query["host"],
        "path": path,
        "key": key,
        "body": body,
    }
    script = """
import json,sys
from uuid import UUID
from sqlalchemy import URL,create_engine
from fastapi.testclient import TestClient
from ara.app import create_app
from ara.documents.runtime import DocumentRuntime
p=json.loads(sys.stdin.read())
engine=create_engine(URL.create('postgresql+psycopg',username=p['username'],
    database=p['database'],query={'host':p['host']}),hide_parameters=True)
try:
    runtime=DocumentRuntime(engine=engine,user_id=UUID(p['user']),project_id=UUID(p['project']),mode='local')
    p['body']['commands'][0].update(list_kind='none',list_id=None)
    with TestClient(create_app(document_runtime=runtime)) as http:
        response=http.post(p['path'],json=p['body'],headers={'Idempotency-Key':p['key']})
        assert response.status_code==200
        print(json.dumps(response.json()))
finally:
    engine.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=30,
        cwd=Path(__file__).resolve().parents[2],
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected
    assert get_docx(runtime, document_id=item.document_id).storage_revision == 2


def test_noop_final_revision_and_same_key_independent_documents(runtime):
    item, body = prepare(runtime)
    body["commands"][0]["style_id"] = "Normal"
    body["expected_storage_revision"] = str(MAX_REVISION - 1)
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE docx_documents SET storage_revision=:r WHERE id=:id"),
            {"r": MAX_REVISION - 1, "id": item.document_id},
        )
    key = str(uuid4())
    path = f"/docx-documents/{item.document_id}/paragraph-commands"
    with TestClient(create_app(document_runtime=runtime)) as http:
        response = http.post(path, json=body, headers={"Idempotency-Key": key})
        assert response.status_code == 200 and response.json()["storage_revision"] == str(
            MAX_REVISION
        )
        assert (
            http.post(path, json=body, headers={"Idempotency-Key": key}).json() == response.json()
        )
        assert (
            http.post(path, json=body, headers={"Idempotency-Key": str(uuid4())}).status_code == 409
        )
        second, request = prepare(runtime)
        assert (
            http.post(
                f"/docx-documents/{second.document_id}/paragraph-commands",
                json=request,
                headers={"Idempotency-Key": key},
            ).status_code
            == 200
        )
    assert get_docx(runtime, document_id=item.document_id).current_data == item.current_data
