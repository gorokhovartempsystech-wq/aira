"""Existing team editor shell, opt-in browser integration with native PR17 clients."""

from pathlib import Path


def install_team_editor(app):
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    root = Path(__file__).parent
    app.mount("/editor/assets", StaticFiles(directory=root / "static"), name="team-editor-assets")
    app.mount(
        "/editor/client",
        StaticFiles(directory=root.parent / "desktop" / "client"),
        name="team-editor-client",
    )

    @app.get("/editor", include_in_schema=False)
    def editor():
        return FileResponse(root / "static" / "editor.html", headers={"Cache-Control": "no-store"})
