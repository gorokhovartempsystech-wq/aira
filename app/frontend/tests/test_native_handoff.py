import ast
import importlib.machinery
import importlib.util
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import test_profile_and_updates as shared
from fastapi.testclient import TestClient

SOURCE = shared.SOURCE

WINDOWS = SOURCE / "app/frontend/packaging/windows"
sys.path.insert(0, str(WINDOWS))
loader = importlib.machinery.SourceFileLoader(
    "onboarding_windows", str(WINDOWS / "aira_launcher.pyw")
)
spec = importlib.util.spec_from_loader(loader.name, loader)
launcher = importlib.util.module_from_spec(spec)
loader.exec_module(launcher)


class NativeRouteTests(unittest.TestCase):
    setUp = shared.RouteTests.setUp
    client = shared.RouteTests.client

    def test_both_native_dispatchers_keep_documents_protected(self):
        async def protected(scope, receive, send):
            if scope["type"] == "lifespan":
                await wrapper.app(scope, receive, send)
                return
            await send({"type": "http.response.start", "status": 451, "headers": []})
            await send({"type": "http.response.body", "body": b"protected"})

        for path in (
            SOURCE / "app/frontend/packaging/macos/serve.py",
            SOURCE / "app/backend/src/ara/model_protection/integration.py",
        ):
            # Execute the actual dispatcher with a synthetic licensed boundary;
            # platform/service imports and real license connections stay unused.
            tree = ast.parse(path.read_text())
            definition = next(
                item
                for item in tree.body
                if isinstance(item, ast.ClassDef) and item.name == "NativeApplication"
            )
            namespace = {}
            exec(
                compile(ast.Module(body=[definition], type_ignores=[]), str(path), "exec"),
                namespace,
            )
            wrapper = object.__new__(namespace["NativeApplication"])
            wrapper.app = self.client().app
            wrapper.protected = protected
            with TestClient(wrapper) as client:
                self.assertEqual(
                    client.get("/aira/onboarding", headers=self.headers).status_code, 200
                )
                self.assertEqual(client.get("/aira/onboarding").status_code, 403)
                self.assertEqual(
                    client.post(
                        "/aira/onboarding/doc", headers=self.headers, json={"status": "completed"}
                    ).status_code,
                    200,
                )
                for route in ("/documents", "/desktop/license", "/aira/onboarding/other"):
                    self.assertEqual(client.get(route, headers=self.headers).status_code, 451)


class WindowsHandoffTests(unittest.TestCase):
    def test_update_bridge_refuses_foreign_page(self):
        window = MagicMock()
        window.get_current_url.return_value = "https://foreign.example.test/aira/"
        ctx = {
            "window": window,
            "server": types.SimpleNamespace(url="http://127.0.0.1:41001/aira/"),
            "closing": False,
            "allow_close": False,
            "request_update": MagicMock(),
        }
        with self.assertRaises(launcher.LaunchError):
            launcher.DesktopApi(ctx).request_update()
        self.assertNotIn("update_requested", ctx)
        window.destroy.assert_not_called()

    def test_update_bridge_requests_save_without_destroying_before_rpc_reply(self):
        window = MagicMock()
        window.get_current_url.return_value = "http://127.0.0.1:41001/aira/#desktop"
        ctx = {
            "window": window,
            "server": types.SimpleNamespace(url="http://127.0.0.1:41001/aira/"),
            "closing": False,
            "allow_close": False,
            "request_update": MagicMock(),
        }
        self.assertTrue(launcher.DesktopApi(ctx).request_update())
        self.assertTrue(ctx["update_requested"])
        ctx["request_update"].assert_called_once()
        window.destroy.assert_not_called()

    def test_already_closing_window_refuses_another_update(self):
        window = MagicMock()
        window.get_current_url.return_value = "http://127.0.0.1:41001/aira/#desktop"
        ctx = {
            "window": window,
            "server": types.SimpleNamespace(url="http://127.0.0.1:41001/aira/"),
            "closing": True,
            "allow_close": False,
            "request_update": MagicMock(),
        }
        self.assertFalse(launcher.DesktopApi(ctx).request_update())
        ctx["request_update"].assert_not_called()
        window.destroy.assert_not_called()

    def test_save_refusal_prevents_restart_and_success_waits_for_shutdown(self):
        import aira_startup

        class Event:
            def __init__(self):
                self.handlers = []

            def __iadd__(self, callback):
                self.handlers.append(callback)
                return self

        for allow_save in (False, True):
            events = []
            window = MagicMock()
            window.events.closing, window.events.closed = Event(), Event()
            api = None

            def create_window(*args, js_api, **kwargs):
                nonlocal api
                api = js_api
                return window

            def close_handshake(window, closed, result, error, *, wait_for_update_ack=False):
                events.append("save")
                result(allow_save)

            def start(*args, **kwargs):
                api._ctx["server"].url = "http://127.0.0.1:41001/aira/"
                window.get_current_url.return_value = api._ctx["server"].url
                api.request_update()

            webview = types.SimpleNamespace(create_window=create_window, start=start)
            with (
                patch.dict(sys.modules, {"webview": webview}),
                patch.object(launcher.ctypes, "windll", MagicMock(), create=True),
                patch.object(launcher.Path, "read_bytes", return_value=b"synthetic-logo"),
                patch.object(aira_startup, "request_window_close", close_handshake),
                patch.object(
                    launcher,
                    "shutdown_backend",
                    side_effect=lambda server: events.append("shutdown"),
                ),
            ):
                requested = launcher.run_desktop(None)
            self.assertEqual(requested, allow_save)
            self.assertEqual(events, ["save", "shutdown"])

    def test_restart_starts_updater_process_after_mutex_is_closed(self):
        events = []
        kernel = MagicMock()
        kernel.CreateMutexW.return_value = 123
        kernel.GetLastError.return_value = 0
        kernel.CloseHandle.side_effect = lambda handle: events.append("release-mutex")
        native = types.SimpleNamespace(kernel32=kernel)
        updates = types.SimpleNamespace(startup_update=lambda *args: False)
        with (
            patch.object(launcher.ctypes, "windll", native, create=True),
            patch.dict(sys.modules, {"aira_updates": updates}),
            patch.object(launcher, "open_log"),
            patch.object(
                launcher,
                "run_desktop",
                side_effect=lambda log: events.append("shutdown-confirmed") or True,
            ),
            patch.object(
                launcher.subprocess,
                "Popen",
                side_effect=lambda *args, **kwargs: events.append("new-process"),
            ),
            patch.object(launcher.sys, "argv", ["aira_launcher.pyw"]),
        ):
            launcher.main()
        self.assertEqual(events, ["shutdown-confirmed", "release-mutex", "new-process"])


if __name__ == "__main__":
    unittest.main()
