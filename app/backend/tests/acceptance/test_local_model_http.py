"""Runtime access/revision gates do not depend on actual model weights."""

from uuid import uuid4

from fastapi.testclient import TestClient
from test_docx_visible_main import source

from ara.app import create_app
from ara.docx_documents import import_docx
from ara.ml_review.http import install_model_review


def test_local_model_revision_scope_and_origin(run_world, tmp_path):
    runtime = run_world["runtimes"]["own"]
    data, _ = source("<w:p><w:r><w:t>Example requirement</w:t></w:r></w:p>")
    identity = uuid4()
    import_docx(runtime, document_id=identity, title="Synthetic", data=data)
    (tmp_path / "manifest.json").write_text("{}")
    app = create_app(document_runtime=runtime)
    install_model_review(app, runtime, tmp_path)
    with TestClient(app) as http:
        path = f"/docx-documents/{identity}/model-reviews"
        assert http.post(path, json={"expected_revision": "2"}).status_code == 409
        assert (
            http.post(
                path,
                json={"expected_revision": "1"},
                headers={"Origin": "https://elsewhere.example"},
            ).status_code
            == 403
        )
        assert (
            http.post(
                path, json={"expected_revision": "1"}, headers={"Host": "evil.example"}
            ).status_code
            == 403
        )
        assert http.post(path, json={"expected_revision": "1", "extra": True}).status_code == 422
        assert (
            http.post(
                f"/docx-documents/{uuid4()}/model-reviews", json={"expected_revision": "1"}
            ).status_code
            == 404
        )


def test_team_editor_save_cas_download_and_origin(run_world):
    from ara.ml_review.editor import install_editor

    runtime = run_world["runtimes"]["own"]
    app = create_app(document_runtime=runtime)
    install_editor(app, runtime)
    identity = str(uuid4())
    payload = {
        "document_id": identity,
        "expected_revision": None,
        "title": "Synthetic editor",
        "text": "Система должна быстро отвечать на запрос.",
    }
    with TestClient(app) as http:
        assert (
            http.post(
                "/editor/documents", json=payload, headers={"Origin": "https://elsewhere.example"}
            ).status_code
            == 403
        )
        first = http.post("/editor/documents", json=payload)
        assert first.status_code == 200
        assert first.json()["storage_revision"] == "1"
        replay = http.post("/editor/documents", json=payload)
        assert replay.status_code == 200
        changed = payload | {"expected_revision": "1", "text": "Изменённый текст требования."}
        assert http.post("/editor/documents", json=changed).json()["storage_revision"] == "2"
        assert http.post("/editor/documents", json=changed).status_code == 409
        downloaded = http.get(f"/docx-documents/{identity}/content")
        assert downloaded.status_code == 200 and downloaded.content.startswith(b"PK")
