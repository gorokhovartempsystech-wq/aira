import base64
import hashlib
import io
import json
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from copy import deepcopy
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import common
import server
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def fixture_feed(key, platform, record):
    root = ET.Element("rss", version="2.0")
    item = ET.SubElement(ET.SubElement(root, "channel"), "item")
    prefix = "{" + common.SPARKLE + "}"
    attributes = {
        "url": common.ORIGIN + "/downloads/" + record["filename"],
        "length": str(record["bytes"]),
        prefix + "shortVersionString": record["version"],
        prefix + "version": str(record["build"])
        if platform == "macos-arm64"
        else record["version"],
        prefix + "edSignature": base64.b64encode(
            key.sign(("synthetic " + platform).encode())
        ).decode(),
    }
    if platform == "macos-arm64":
        ET.SubElement(item, prefix + "minimumSystemVersion").text = "14.0"
    else:
        attributes[prefix + "os"] = "windows-x64"
        attributes[prefix + "installerArguments"] = "/SILENT /NORESTART /AIRAUPDATE=1"
    ET.SubElement(item, "enclosure", attributes)
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if platform == "macos-arm64":
        signature = base64.b64encode(key.sign(data))
        data += (
            b"<!-- sparkle-signatures:\nedSignature: "
            + signature
            + b"\nlength: "
            + str(len(data)).encode()
            + b"\n-->\n"
        )
    return data


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "state"
        self.downloads = Path(self.directory.name) / "downloads"
        self.root.mkdir()
        self.downloads.mkdir()
        self.key = Ed25519PrivateKey.generate()
        self.public = base64.b64encode(
            self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ).decode()
        self.claims = {"sha": "a" * 40, "run_number": "3", "run_id": "100", "run_attempt": "1"}
        self.version, self.build, _ = server.identity(self.claims)
        self.document = {
            "sha": self.claims["sha"],
            "version": self.version,
            "build": self.build,
            "platforms": {},
            "feeds": {},
        }
        for platform in common.PLATFORMS:
            data = ("synthetic " + platform).encode()
            expected = hashlib.sha256(data).hexdigest()
            uploaded = server.upload(
                self.root, self.claims, platform, io.BytesIO(data), len(data), expected
            )
            record = {
                **uploaded,
                "platform": platform,
                "version": self.version,
                "build": self.build,
                "sha": self.claims["sha"],
            }
            self.document["platforms"][platform] = record
            self.document["feeds"][platform] = base64.b64encode(
                fixture_feed(self.key, platform, record)
            ).decode()

    def promote(self, document=None, claims=None):
        return server.promote(
            self.root, self.downloads, claims or self.claims, document or self.document, self.public
        )

    def test_signed_pair_is_atomic_and_retry_is_idempotent(self):
        self.assertEqual(list(self.downloads.iterdir()), [])
        receipt = self.promote()
        pointer = (self.root / "current").resolve()
        self.assertEqual(receipt["sha"], self.claims["sha"])
        self.assertEqual(self.promote(), receipt)
        self.assertEqual((self.root / "current").resolve(), pointer)
        self.assertEqual(json.loads((pointer / "releases.json").read_text()), receipt)
        for platform in common.PLATFORMS:
            record = receipt["platforms"][platform]
            self.assertEqual(common.digest(self.downloads / record["filename"]), record["sha256"])
            self.assertEqual(
                (pointer / (platform + ".xml")).read_bytes(),
                base64.b64decode(self.document["feeds"][platform]),
            )

    def test_one_missing_platform_cannot_replace_release(self):
        good = self.promote()
        bad = deepcopy(self.document)
        del bad["platforms"]["windows-x64"]
        with self.assertRaises(ValueError):
            self.promote(bad)
        self.assertEqual(server.current(self.root), good)

    def test_forged_signature_does_not_publish_either_platform(self):
        bad = deepcopy(self.document)
        feed = base64.b64decode(bad["feeds"]["windows-x64"])
        signature = base64.b64encode(self.key.sign(b"synthetic windows-x64"))
        feed = feed.replace(signature, base64.b64encode(b"x" * 64))
        bad["feeds"]["windows-x64"] = base64.b64encode(feed).decode()
        with self.assertRaises(InvalidSignature):
            self.promote(bad)
        self.assertFalse((self.root / "current").exists())
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_unsigned_mac_feed_is_rejected(self):
        bad = deepcopy(self.document)
        feed = base64.b64decode(bad["feeds"]["macos-arm64"]).split(b"<!-- sparkle-signatures:")[0]
        bad["feeds"]["macos-arm64"] = base64.b64encode(feed).decode()
        with self.assertRaises(ValueError):
            self.promote(bad)
        self.assertFalse((self.root / "current").exists())

    def test_source_tampering_and_unsafe_names_are_rejected(self):
        for field, value in [("sha", "b" * 40), ("filename", "../../escape")]:
            bad = deepcopy(self.document)
            bad["platforms"]["windows-x64"][field] = value
            with self.assertRaises(ValueError):
                self.promote(bad)
        source = self.root / "uploads/100-1" / common.filename("windows-x64", self.version)
        source.write_bytes(b"changed bytes")
        with self.assertRaises(ValueError):
            self.promote()
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_stale_runs_and_changed_replays_are_rejected(self):
        receipt = self.promote()
        with self.assertRaises(ValueError):
            self.promote(claims={**self.claims, "run_id": "99"})
        with self.assertRaises(ValueError):
            self.promote(claims={**self.claims, "sha": "b" * 40})
        self.assertEqual(server.current(self.root), receipt)

    def test_incorrect_and_truncated_uploads_never_become_public(self):
        for data, length, expected in [(b"small", 8, "0" * 64), (b"bad", 3, "0" * 64)]:
            with self.assertRaises(ValueError):
                server.upload(
                    self.root, self.claims, "windows-x64", io.BytesIO(data), length, expected
                )
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_existing_installer_url_cannot_be_overwritten(self):
        name = common.filename("windows-x64", self.version)
        (self.downloads / name).write_bytes(b"previous immutable release")
        with self.assertRaises(ValueError):
            self.promote()
        self.assertEqual((self.downloads / name).read_bytes(), b"previous immutable release")
        self.assertFalse((self.root / "current").exists())

    def test_unauthorized_http_cannot_write(self):
        handler = type(
            "FixtureHandler", (server.Handler,), {"root": self.root, "downloads": self.downloads}
        )
        http = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=http.serve_forever)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{http.server_port}/_deploy/releases/promote",
                data=b"{}",
                method="POST",
            )
            with self.assertRaises(HTTPError) as failure:
                urlopen(request, timeout=3)
            self.assertEqual(failure.exception.code, 401)
            self.assertFalse((self.root / "current").exists())
        finally:
            http.shutdown()
            thread.join()
            http.server_close()

    def test_authenticated_stream_upload_and_promotion_http_contract(self):
        class FixtureVerifier:
            def verify(inner, token):
                if token != "synthetic-token":
                    raise ValueError("token")
                return self.claims

        handler = type(
            "FixtureHandler",
            (server.Handler,),
            {
                "root": self.root,
                "downloads": self.downloads,
                "verifier": FixtureVerifier(),
            },
        )
        http = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=http.serve_forever)
        thread.start()
        original = server.promote
        try:
            origin = f"http://127.0.0.1:{http.server_port}" + server.ENDPOINT
            data = b"synthetic windows-x64"
            request = Request(
                origin + "/artifact/windows-x64",
                data=io.BytesIO(data),
                method="POST",
                headers={
                    "Authorization": "Bearer synthetic-token",
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(len(data)),
                    "X-Aira-SHA256": hashlib.sha256(data).hexdigest(),
                },
            )
            with urlopen(request, timeout=3) as response:
                self.assertEqual(json.load(response)["sha256"], hashlib.sha256(data).hexdigest())
            request = Request(
                origin + "/promote",
                data=json.dumps(self.document).encode(),
                method="POST",
                headers={
                    "Authorization": "Bearer synthetic-token",
                    "Content-Type": "application/json",
                },
            )
            with (
                patch.object(
                    server,
                    "promote",
                    side_effect=lambda root, downloads, claims, document: original(
                        root, downloads, claims, document, self.public
                    ),
                ),
                urlopen(request, timeout=3) as response,
            ):
                self.assertEqual(json.load(response)["version"], self.version)
        finally:
            http.shutdown()
            thread.join()
            http.server_close()


if __name__ == "__main__":
    unittest.main()
