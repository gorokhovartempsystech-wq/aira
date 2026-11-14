"""Installer wiring for protected bundles; no secrets or network on import."""

from ara.desktop.access import LicensedApplication
from ara.licensing.client import ActivationStore, LicenseClient

from .bundle import configuration
from .client import ModelAccessClient


def make_license_client(origin, license_directory, model_directory, **kwargs):
    selected = configuration(model_directory)
    access = ModelAccessClient(origin, *selected) if selected is not None else None
    return LicenseClient(origin, ActivationStore(license_directory), model_access=access, **kwargs)


class NativeApplication:
    """Public page/assets; protected product API uses the native session token."""

    def __init__(self, app, client, origin, token):
        self.app = app
        self.protected = LicensedApplication(app, client, origin=origin, session_token=token)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and (
            path in {"/aira", "/aira/", "/aira/diagnostics/log", "/aira/diagnostics/client",
                     "/aira/onboarding", "/aira/onboarding/start", "/aira/onboarding/doc", "/aira/updates"}
            or path.startswith(("/aira/assets/", "/aira/client/"))
        ):
            await self.app(scope, receive, send)
            return
        await self.protected(scope, receive, send)
