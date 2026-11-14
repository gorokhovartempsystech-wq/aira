import concurrent.futures
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from fastapi import FastAPI
from fastapi.testclient import TestClient

FRONTEND = Path(__file__).resolve().parents[1]
SOURCE = FRONTEND.parents[1]
sys.path.insert(0, str(FRONTEND))
host = importlib.import_module("aira_host")

NS = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
ORIGIN = "https://updates.example.test"
TOKEN = "ab" * 32  # synthetic native capability


def feed(*releases, platform="windows-x64"):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    for version, build in releases:
        item = ET.SubElement(channel, "item")
        ET.SubElement(
            item,
            "enclosure",
            {
                "url": ORIGIN + "/downloads/AIRA-" + version,
                NS + "shortVersionString": version,
                NS + "version": str(build),
                NS + "edSignature": "synthetic-signature",
                NS + "os": platform,
            },
        )
    return ET.tostring(root)


def config(platform="windows-x64", version="0.2.7", build="7"):
    return dict(
        feed_url=ORIGIN + "/updates/" + platform + ".xml",
        platform=platform,
        version=version,
        build=build,
    )


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "profile/onboarding.json"

    def test_restart_preserves_each_tour_separately(self):
        store = host.OnboardingStore(self.path)
        self.assertEqual(store.read(), {"start": "new", "doc": "new"})
        store.mark("start", "completed")
        restarted = host.OnboardingStore(self.path)
        self.assertEqual(restarted.read(), {"start": "completed", "doc": "new"})
        restarted.mark("doc", "completed")
        self.assertEqual(
            host.OnboardingStore(self.path).read(), {"start": "completed", "doc": "completed"}
        )

    def test_dismissal_is_distinct_and_cannot_undo_completion(self):
        store = host.OnboardingStore(self.path)
        store.mark("start", "dismissed")
        self.assertEqual(store.read()["start"], "dismissed")
        store.mark("start", "completed")
        store.mark("start", "dismissed")
        self.assertEqual(store.read()["start"], "completed")

    def test_concurrent_completions_do_not_lose_other_tour(self):
        store = host.OnboardingStore(self.path)
        with concurrent.futures.ThreadPoolExecutor() as pool:
            list(pool.map(lambda kind: store.mark(kind, "completed"), ("start", "doc") * 5))
        self.assertEqual(store.read(), {"start": "completed", "doc": "completed"})

    def test_failed_atomic_replace_preserves_previous_state(self):
        store = host.OnboardingStore(self.path)
        store.mark("start", "completed")
        before = self.path.read_bytes()
        with patch("os.replace", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                store.mark("doc", "completed")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob(".onboarding-*")), [])

    def test_corrupt_profile_is_reported_and_explicit_completion_repairs_it(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b"invalid json")
        store = host.OnboardingStore(self.path)
        with self.assertRaises(ValueError):
            store.read()
        self.assertEqual(store.mark("doc", "completed"), {"start": "new", "doc": "completed"})

    def test_bad_choice_does_not_create_profile(self):
        for kind, status in (("all", "completed"), ("start", True), ("doc", "new")):
            with self.assertRaises(ValueError):
                host.OnboardingStore(self.path).mark(kind, status)
        self.assertFalse(self.path.exists())

    def test_unconfigured_profile_does_not_write_to_working_directory(self):
        with self.assertRaises(OSError):
            host.OnboardingStore(None).mark("start", "completed")


class FeedTests(unittest.TestCase):
    def test_windows_compares_numerically(self):
        state = host.UpdateFeed(config(version="0.2.9")).parse(feed(("0.2.10", "0.2.10")))
        self.assertEqual(state["status"], "available")
        self.assertEqual(state["latest_version"], "0.2.10")

    def test_older_release_never_downgrades(self):
        state = host.UpdateFeed(config()).parse(feed(("0.2.6", "0.2.6")))
        self.assertEqual(state["status"], "current")

    def test_mac_same_version_new_build_is_update(self):
        state = host.UpdateFeed(config("macos-arm64")).parse(
            feed(("0.2.7", "8"), platform="macos-arm64")
        )
        self.assertEqual(state["status"], "available")

    def test_mac_older_build_or_version_never_downgrades(self):
        for version, build in (("0.2.7", "6"), ("0.2.6", "20")):
            state = host.UpdateFeed(config("macos-arm64")).parse(
                feed((version, build), platform="macos-arm64")
            )
            self.assertEqual(state["status"], "current")

    def test_latest_item_selected_independent_of_feed_order(self):
        state = host.UpdateFeed(config()).parse(feed(("0.2.10", "0.2.10"), ("0.2.8", "0.2.8")))
        self.assertEqual(state["latest_version"], "0.2.10")

    def test_malformed_or_foreign_feed_cannot_claim_current(self):
        raw = feed(("0.2.8", "0.2.8"))
        for value in (
            b"",
            b"<rss/>",
            b"<!DOCTYPE rss><rss/>",
            b"x" * 65537,
            raw.replace(ORIGIN.encode(), b"https://foreign.example.test"),
            raw.replace(b"windows-x64", b"macos-arm64"),
            raw.replace(b"synthetic-signature", b""),
            raw.replace(b"0.2.8", b"<bad"),
        ):
            with self.subTest(value=value[:45]):
                with self.assertRaises(ValueError):
                    host.UpdateFeed(config()).parse(value)

    def test_cache_and_manual_refresh(self):
        import io

        class Opener:
            calls = []

            def open(self, request, timeout):
                self.calls.append((request, timeout))
                return io.BytesIO(feed(("0.2.8", "0.2.8")))

        opener = Opener()
        updater = host.UpdateFeed(config())
        with patch("urllib.request.build_opener", return_value=opener):
            updater.snapshot()
            updater.snapshot()
            updater.snapshot(refresh=True)
        self.assertEqual(len(opener.calls), 2)
        request, timeout = opener.calls[0]
        self.assertEqual(timeout, 5)
        self.assertIsNone(request.data)
        self.assertEqual(request.full_url, ORIGIN + "/updates/windows-x64.xml")
        self.assertNotIn("Authorization", request.headers)

    def test_insecure_or_unconfigured_feed_never_fetches(self):
        for value in (
            None,
            {**config(), "feed_url": "http://updates.example.test/updates/windows-x64.xml"},
            {**config(), "feed_url": ORIGIN + "/updates/windows-x64.xml?token=synthetic"},
        ):
            with patch("urllib.request.build_opener") as opener:
                with self.assertRaises(ValueError):
                    host.UpdateFeed(value).snapshot()
                opener.assert_not_called()


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "onboarding.json"
        self.headers = {"X-AIRA-Session": TOKEN}
        self.backend = Path(self.temp.name) / "backend"
        (self.backend / "src/ara/desktop/client").mkdir(parents=True)

    def client(self, port=41001):
        app = FastAPI()
        with patch.object(host, "BACKEND", self.backend):
            host.frontend_routes(
                app,
                port,
                token=TOKEN,
                native_only=True,
                onboarding_path=self.path,
                app_update=config(),
            )
        return TestClient(app)

    def test_different_port_and_process_route_restore(self):
        with self.client() as client:
            self.assertEqual(
                client.post(
                    "/aira/onboarding/start", headers=self.headers, json={"status": "completed"}
                ).status_code,
                200,
            )
        with self.client(41099) as client:
            response = client.get("/aira/onboarding", headers=self.headers)
            self.assertEqual(response.json(), {"start": "completed", "doc": "new"})
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(client.get("/aira/connection").status_code, 404)

    def test_missing_or_wrong_capability_cannot_read_or_write(self):
        with self.client() as client, patch.object(host.UpdateFeed, "snapshot") as network:
            for headers in ({}, {"X-AIRA-Session": "wrong"}):
                for method, path in (
                    ("GET", "/aira/onboarding"),
                    ("POST", "/aira/onboarding/start"),
                    ("GET", "/aira/updates"),
                ):
                    response = client.request(method, path, headers=headers)
                    self.assertEqual(response.status_code, 403)
            network.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_bad_json_and_oversized_choice_do_not_write(self):
        with self.client() as client:
            for content in ("[1]", "{}", '{"status": true}', "x" * 129):
                response = client.post(
                    "/aira/onboarding/start", headers=self.headers, content=content
                )
                self.assertEqual(response.status_code, 422)
        self.assertFalse(self.path.exists())

    def test_read_and_write_disk_failures_are_explicit(self):
        with (
            self.client() as client,
            patch.object(host.OnboardingStore, "read", side_effect=OSError),
        ):
            self.assertEqual(client.get("/aira/onboarding", headers=self.headers).status_code, 503)
            self.assertEqual(
                client.post(
                    "/aira/onboarding/start", headers=self.headers, json={"status": "completed"}
                ).status_code,
                503,
            )

    def test_feed_failure_is_not_reported_as_latest(self):
        with (
            self.client() as client,
            patch.object(host.UpdateFeed, "snapshot", side_effect=OSError),
        ):
            response = client.get("/aira/updates", headers=self.headers)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["code"], "update_check_unavailable")


if __name__ == "__main__":
    unittest.main()
