"""Portable updater integration checks. Native acceptance remains OS-specific."""

import base64
import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from make_appcast import SPARKLE, appcast

spec = importlib.util.spec_from_file_location(
    "aira_updates", Path(__file__).parents[1] / "windows/aira_updates.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Function:
    def __init__(self, impl):
        self.impl = impl

    def __call__(self, *args):
        return self.impl(*args)


class FakeDLL:
    def __init__(self, event, *, accepted_key=1):
        self.calls = []
        self.callbacks = {}
        self.event = event
        self.accepted_key = accepted_key

    def __getattr__(self, name):
        def call(*args):
            self.calls.append(name)
            if name.endswith("_callback"):
                self.callbacks[name] = args[0]
            if name.endswith("set_eddsa_public_key"):
                return self.accepted_key
            if name.endswith("check_update_with_ui_and_install") and self.event:
                if self.event == "shutdown_request":
                    assert self.callbacks["win_sparkle_set_can_shutdown_callback"]() == 1
                self.callbacks["win_sparkle_set_" + self.event + "_callback"]()

        return Function(call)


class Updates(unittest.TestCase):
    def test_windows_outcomes_cleanup_before_backend(self):
        for event in [
            "did_not_find_update",
            "error",
            "update_cancelled",
            "update_dismissed",
            "shutdown_request",
            None,
        ]:
            with self.subTest(event=event), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)
                (path / "release-config.json").write_text(
                    json.dumps(
                        {
                            "origin": "https://updates.example.test",
                            "public_key": base64.b64encode(b"x" * 32).decode(),
                        }
                    )
                )
                dll = FakeDLL(event)
                installed = module.startup_update(
                    path, "0.2.4", loader=lambda _: dll, wait_seconds=0
                )
                self.assertEqual(installed, event == "shutdown_request")
                self.assertEqual(dll.calls[-1], "win_sparkle_cleanup")
                self.assertLess(
                    dll.calls.index("win_sparkle_set_eddsa_public_key"),
                    dll.calls.index("win_sparkle_init"),
                )

    def test_bad_key_cannot_start_updater(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "release-config.json").write_text(
                json.dumps(
                    {
                        "origin": "https://updates.example.test",
                        "public_key": base64.b64encode(b"x" * 32).decode(),
                    }
                )
            )
            dll = FakeDLL(None, accepted_key=0)
            with self.assertRaises(ValueError):
                module.startup_update(path, "0.2.4", loader=lambda _: dll)
            self.assertNotIn("win_sparkle_init", dll.calls)

    def test_feed_contains_signed_versioned_platform_artifact(self):
        for platform in ["macos-arm64", "windows-x64"]:
            raw = appcast(
                platform=platform,
                version="0.2.4",
                build=3,
                url="https://updates.example.test/downloads/test",
                size=123,
                signature=base64.b64encode(b"x" * 64).decode(),
            )
            item = ET.fromstring(raw).find("channel/item/enclosure")
            self.assertEqual(item.attrib["length"], "123")
            self.assertEqual(
                item.attrib[f"{{{SPARKLE}}}version"], "3" if platform == "macos-arm64" else "0.2.4"
            )
            self.assertIn(f"{{{SPARKLE}}}edSignature", item.attrib)

    def test_feed_rejects_unsigned_or_insecure_artifact(self):
        base = dict(
            platform="macos-arm64",
            version="0.2.4",
            build=3,
            url="https://updates.example.test/downloads/test",
            size=123,
            signature=base64.b64encode(b"x" * 64).decode(),
        )
        for overrides in [
            {"url": "http://example.test/a"},
            {"signature": ""},
            {"build": 0},
            {"platform": "macos-intel"},
            {"version": "../0.2.4"},
            {"size": 0},
        ]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                appcast(**(base | overrides))


if __name__ == "__main__":
    unittest.main()
