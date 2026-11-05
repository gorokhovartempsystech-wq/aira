"""Opt-in cell checkpoints survive close/reopen; legacy default stays body-only."""

import pytest
from fastapi.testclient import TestClient
from test_docx_editor_http import command, control, opened, path, root
from test_docx_text_edit import seed
from test_docx_visible_word import parts, source

from ara.app import create_app
from ara.config import ConfigurationError
from ara.documents.storage import DocumentError
from ara.docx_editor import EditorRegistry


def test_table_edit_checkpoint_close_recover_save_export(run_world):
    runtime = run_world["runtimes"]["own"]
    raw = source("table")
    item = seed(run_world, raw)
    with TestClient(create_app(document_runtime=runtime, table_editor=True)) as http:
        v, _ = opened(http, item)
        response = http.post(path(item, v) + "/commands", json=command(v, "insert_text", "Новое "))
        assert response.status_code == 200
        changed = response.json()
        req = control(changed)
        response = http.post(path(item, changed) + "/checkpoint", json=req)
        assert response.status_code == 200 and response.json()["document"]["is_dirty"]
        checkpointed = response.json()
        assert http.post(path(item, changed) + "/checkpoint", json=req).json() == checkpointed
        response = http.post(path(item, checkpointed) + "/close", json=control(checkpointed))
        assert response.status_code == 200 and response.json()["kind"] == "closed"
    with TestClient(create_app(document_runtime=runtime, table_editor=True)) as http:
        restored, _ = opened(http, item, "recover")
        assert restored["document"]["session_revision"] == "0" and restored["document"]["is_dirty"]
        full = http.get(path(item, restored) + "/view").json()
        assert full["projection"]["blocks"][0]["rows"][0]["cells"][0]["blocks"][0][
            "text"
        ].startswith("Новое ")
        saved = http.post(path(item, restored) + "/save", json=control(restored))
        assert saved.status_code == 200 and not saved.json()["document"]["is_dirty"]
        exported = http.get(root(item) + "/content").content
        a, b = parts(raw), parts(exported)
        assert a.keys() == b.keys() and a["word/document.xml"] != b["word/document.xml"]
        assert all(a[k] == b[k] for k in a if k != "word/document.xml")


def test_legacy_http_refusal_remains_and_opt_in_can_open_same_original(run_world):
    runtime = run_world["runtimes"]["own"]
    item = seed(run_world, source("merged_table"))
    with TestClient(create_app(document_runtime=runtime)) as http:
        from uuid import uuid4

        status = http.get(root(item) + "/editor-recovery").json()
        body = dict(
            registry_id=status["registry_id"],
            client_open_id=str(uuid4()),
            expected_open_sequence=status["open_sequence"],
            expected_checkpoint_revision=status["checkpoint_revision"],
            mode="current",
        )
        response = http.post(root(item) + "/editor-sessions", json=body)
        assert (
            response.status_code == 422 and response.json()["code"] == "editor_document_unsupported"
        )
    with TestClient(create_app(document_runtime=runtime, table_editor=True)) as http:
        view, _ = opened(http, item)
        assert view["document"]["is_dirty"] is False
        assert http.get(root(item) + "/content").content == source("merged_table")


@pytest.mark.parametrize("value", [None, 1, "tables", []])
def test_opt_in_rejects_non_boolean_configuration_before_work(run_world, value):
    with pytest.raises(DocumentError) as caught:
        EditorRegistry(run_world["runtimes"]["own"], table_editor=value)
    assert caught.value.code == "validation_error"
    with pytest.raises(ConfigurationError):
        create_app(document_runtime=run_world["runtimes"]["own"], table_editor=value)


def test_owned_merged_cell_edit_check_preserves_source_parts(tmp_path):
    import sys

    if sys.platform != "darwin":
        pytest.skip("native owned macOS composition")
    from test_desktop_composition import activate, running
    from test_desktop_server import http_for
    from test_desktop_structured_review import imported, send
    from test_desktop_word_review import check, word_config

    raw = source("merged_table")
    with running(word_config(tmp_path)) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        item = imported(http, raw)
        view, _ = opened(http, item)
        view = send(http, item, view, "insert_text", "Новая ячейка ")
        _, _, _, result = check(http, item, view)
        assert result["result"]["findings"][0]["primary"]["quote"].startswith("Новая ячейка ")
        a, b = parts(raw), parts(http.get(root(item) + "/content").content)
        assert a.keys() == b.keys() and a["word/document.xml"] != b["word/document.xml"]
        assert all(a[k] == b[k] for k in a if k != "word/document.xml")
