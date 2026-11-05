from fastapi import FastAPI
from fastapi.testclient import TestClient

from ara.team_editor import install_team_editor


def test_team_shell_and_pinned_native_clients_are_served_locally():
    app = FastAPI()
    install_team_editor(app)
    with TestClient(app) as client:
        shell = client.get("/editor")
        assert shell.status_code == 200
        assert shell.headers["cache-control"] == "no-store"
        assert "/editor/assets/editor.mjs" in shell.text
        for path in (
            "/editor/assets/editor.css",
            "/editor/assets/editor.mjs",
            "/editor/assets/text-change.mjs",
            "/editor/client/docx-session.mjs",
            "/editor/client/analysis-session.mjs",
            "/editor/client/review-session.mjs",
        ):
            assert client.get(path).status_code == 200
        assert client.get("/editor/assets/missing-file").status_code == 404
