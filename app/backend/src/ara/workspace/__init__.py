"""Static local workspace, installed explicitly and read only on HTTP requests."""


def install_workspace(app) -> None:
    from fastapi import Response

    def asset(name, mime):
        from importlib.resources import files

        data = files(__package__).joinpath("static", name).read_bytes()
        return Response(
            data,
            media_type=mime,
            headers={
                "Content-Type": f"{mime}; charset=utf-8",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; img-src 'none'; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'"
                ),
            },
        )

    @app.get("/workspace", include_in_schema=False)
    def workspace():
        return asset("index.html", "text/html")

    @app.get("/workspace/assets/app.css", include_in_schema=False)
    def stylesheet():
        return asset("app.css", "text/css")

    @app.get("/workspace/assets/app.js", include_in_schema=False)
    def javascript():
        return asset("app.js", "application/javascript")

    @app.get("/workspace/assets/autosave.js", include_in_schema=False)
    def autosave_javascript():
        return asset("autosave.js", "application/javascript")

    @app.get("/workspace/assets/history.js", include_in_schema=False)
    def history_javascript():
        return asset("history.js", "application/javascript")

    @app.get("/workspace/assets/tabs.js", include_in_schema=False)
    def tabs_javascript():
        return asset("tabs.js", "application/javascript")
