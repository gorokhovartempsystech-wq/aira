"""Native Windows admission; importing does not start services or read secrets."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from ara.desktop.access import LicensedApplication
from ara.licensing.client import ActivationStore, LicenseClient


def create_license_client(config_path, store_root):
    """Use the installer's public HTTPS origin, never a profile override."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    return LicenseClient(config["origin"], ActivationStore(Path(store_root)))


def trusted_page(current, expected):
    if not isinstance(current, str) or not isinstance(expected, str):
        return False
    try:
        page, target = urlsplit(current), urlsplit(expected)
        return (
            target.scheme == page.scheme == "http"
            and target.hostname == page.hostname == "127.0.0.1"
            and target.port == page.port
            and target.port is not None
            and target.path == page.path == "/aira/"
            and not page.username
            and not page.password
            and not page.query
            and not target.query
        )
    except ValueError:
        return False


class NativeApplication:
    """Public UI assets; document and license APIs use the existing strict gate."""

    def __init__(self, app, client, *, origin, token):
        self.app = app
        self.protected = LicensedApplication(app, client, origin=origin, session_token=token)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        public = path in {"/aira", "/aira/"} or path.startswith(("/aira/assets/", "/aira/client/"))
        diagnostic = path in {"/aira/diagnostics/log", "/aira/diagnostics/client"}
        if scope["type"] == "http" and (
            (scope.get("method") in {"GET", "HEAD"} and public) or diagnostic
        ):
            await self.app(scope, receive, send)
            return
        await self.protected(scope, receive, send)
