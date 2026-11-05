"""A real admitted PostgreSQL editor save completes while its native host drains."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

from test_desktop_server import api, http_for, license_client, wait_for
from test_docx_editor_http import command, control, opened, path
from test_docx_text_edit import seed
from test_licensing_client_runtime import done
from test_licensing_policy import synthetic_key

from ara.app import create_app
from ara.docx_documents import get_docx


def test_host_shutdown_preserves_accepted_editor_commit(run_world, tmp_path, monkeypatch):
    runtime = run_world["runtimes"]["own"]
    item = seed(run_world)
    app = create_app(document_runtime=runtime)
    client = license_client(tmp_path / "license")
    host = api().LoopbackServer(app, client)
    entered, release = Event(), Event()
    original = app.state.docx_editor_registry.save

    def held(**kwargs):
        entered.set()
        assert release.wait(5)
        return original(**kwargs)

    monkeypatch.setattr(app.state.docx_editor_registry, "save", held)
    try:
        host.start()
        wait_for(lambda: host.view().phase == "ready")
        wait_for(lambda: client.view().phase != "checking")
        with http_for(host.connection()) as http, ThreadPoolExecutor(max_workers=1) as pool:
            assert (
                http.post(
                    "/desktop/license/activate", json={"license_key": synthetic_key()}
                ).status_code
                == 202
            )
            assert done(client).phase == "active"
            view, _ = opened(http, item)
            response = http.post(
                path(item, view) + "/commands",
                json=command(view, "insert_text", "Finish accepted save "),
            )
            assert response.status_code == 200
            view = response.json()
            expected = app.state.docx_editor_registry.snapshot(
                document_id=item.document_id, session_id=UUID(view["session_id"])
            ).editor.document.data
            future = pool.submit(http.post, path(item, view) + "/save", json=control(view))
            assert entered.wait(3)
            assert not host.shutdown(timeout=0.02)
            assert get_docx(runtime, document_id=item.document_id) == item
            release.set()
            saved = future.result(timeout=4)
            assert saved.status_code == 200 and saved.json()["document"]["is_dirty"] is False
        assert host.shutdown(timeout=5)
        current = get_docx(runtime, document_id=item.document_id)
        assert current.current_data == expected and current.original_data == item.original_data
        assert current.storage_revision == item.storage_revision + 1
    finally:
        release.set()
        assert host.shutdown(timeout=5)
        client.close()
