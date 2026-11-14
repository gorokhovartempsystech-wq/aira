"""Receive tested, signed desktop releases; no signing key is stored on this server."""

import base64
import hashlib
import importlib.util
import json
import mmap
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from common import (
    ORIGIN,
    PLATFORMS,
    PUBLIC_KEY,
    SPARKLE,
    build_for_run,
    digest,
    filename,
    version_for_run,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path("/var/lib/aira-release-publish")
DOWNLOADS = Path("/srv/aira-public/downloads")
ENDPOINT = "/_deploy/releases"
WORKFLOW = "gorokhovartempsystech-wq/aira/.github/workflows/desktop-release.yml@refs/heads/main"
MAX_ARTIFACT = 1800 * 1024**2
MAX_METADATA = 128 * 1024


def identity(claims):
    version = version_for_run(claims["run_number"])
    build = build_for_run(claims["run_number"])
    return version, build, [int(claims[k]) for k in ("run_id", "run_attempt")]


def current(root):
    path = root / "current/releases.json"
    return json.loads(path.read_text()) if path.exists() else None


def check_order(root, claims):
    version, build, run = identity(claims)
    previous = current(root)
    if previous and run < previous.get("run", [0, 0]):
        raise ValueError("stale run")
    if previous and run == previous.get("run") and previous["sha"] != claims["sha"]:
        raise ValueError("run source mismatch")
    return version, build, run


def upload(root, claims, platform, stream, length, expected):
    version, _, run = check_order(root, claims)
    name = filename(platform, version)
    if type(length) is not int or not 0 < length <= MAX_ARTIFACT:
        raise ValueError("artifact length")
    if not re.fullmatch("[0-9a-f]{64}", expected):
        raise ValueError("artifact digest")
    if shutil.disk_usage(root).free < length + 256 * 1024**2:
        raise ValueError("insufficient staging space")
    stage = root / "uploads" / (str(run[0]) + "-" + str(run[1]))
    stage.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix="upload-", dir=stage)
    temporary = Path(temporary)
    try:
        actual = hashlib.sha256()
        remaining = length
        with os.fdopen(descriptor, "wb") as output:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("short upload")
                actual.update(chunk)
                output.write(chunk)
                remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
        if actual.hexdigest() != expected:
            raise ValueError("upload checksum mismatch")
        target = stage / name
        if target.exists():
            if target.stat().st_size != length or digest(target) != expected:
                raise ValueError("staged artifact is immutable")
        else:
            os.link(temporary, target)
        return {"filename": name, "bytes": length, "sha256": expected}
    finally:
        temporary.unlink(missing_ok=True)


def signed_feed(platform, feed, record, version, build, key):
    if not 0 < len(feed) < 32768 or b"<!DOCTYPE" in feed or b"<!ENTITY" in feed:
        raise ValueError("feed encoding")
    root = ET.fromstring(feed)
    items = root.findall("channel/item")
    if len(items) != 1:
        raise ValueError("one release item required")
    enclosures = items[0].findall("enclosure")
    if len(enclosures) != 1:
        raise ValueError("one enclosure required")
    attrs = enclosures[0].attrib
    expected = {
        "url": ORIGIN + "/downloads/" + record["filename"],
        "length": str(record["bytes"]),
        "{" + SPARKLE + "}shortVersionString": version,
        "{" + SPARKLE + "}version": str(build) if platform == "macos-arm64" else version,
    }
    if any(attrs.get(k) != v for k, v in expected.items()):
        raise ValueError("feed artifact mismatch")
    signature = base64.b64decode(attrs["{" + SPARKLE + "}edSignature"], validate=True)
    if len(signature) != 64:
        raise ValueError("installer signature")
    if platform == "macos-arm64":
        if items[0].findtext("{" + SPARKLE + "}minimumSystemVersion") != "14.0":
            raise ValueError("Mac minimum system version")
        signed = re.search(
            rb"<!-- sparkle-signatures:\s*edSignature: ([A-Za-z0-9+/=]+)"
            rb"\s*length: ([0-9]+)\s*-->\s*$",
            feed,
        )
        if signed is None or int(signed[2]) != signed.start():
            raise ValueError("signed Mac feed required")
        key.verify(base64.b64decode(signed[1], validate=True), feed[: signed.start()])
    else:
        if attrs.get("{" + SPARKLE + "}os") != "windows-x64":
            raise ValueError("Windows architecture")
        if attrs.get("{" + SPARKLE + "}installerArguments") != "/SILENT /NORESTART /AIRAUPDATE=1":
            raise ValueError("installer arguments")
    return signature


def promote(root, downloads, claims, document, public_key=PUBLIC_KEY):
    version, build, run = check_order(root, claims)
    if set(document) != {"sha", "version", "build", "platforms", "feeds"}:
        raise ValueError("release schema")
    if (document["sha"], document["version"], document["build"]) != (claims["sha"], version, build):
        raise ValueError("release identity")
    if set(document["platforms"]) != set(PLATFORMS) or set(document["feeds"]) != set(PLATFORMS):
        raise ValueError("both tested platforms required")
    previous = current(root)
    if previous and any(
        tuple(map(int, p["version"].split("."))) > tuple(map(int, version.split(".")))
        for p in previous["platforms"].values()
    ):
        raise ValueError("release downgrade")
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
    stage = root / "uploads" / (str(run[0]) + "-" + str(run[1]))
    records, feeds = {}, {}
    for platform in PLATFORMS:
        record = document["platforms"][platform]
        name = filename(platform, version)
        source = stage / name
        if set(record) != {"sha", "version", "build", "platform", "filename", "bytes", "sha256"}:
            raise ValueError("artifact receipt schema")
        if (
            record["sha"],
            record["version"],
            record["build"],
            record["platform"],
            record["filename"],
        ) != (claims["sha"], version, build, platform, name):
            raise ValueError("artifact receipt identity")
        if (
            not source.is_file()
            or source.stat().st_size != record["bytes"]
            or digest(source) != record["sha256"]
        ):
            raise ValueError("staged artifact mismatch")
        feed = base64.b64decode(document["feeds"][platform], validate=True)
        signature = signed_feed(platform, feed, record, version, build, key)
        with (
            source.open("rb") as stream,
            mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data,
        ):
            key.verify(signature, data)
        feeds[platform] = feed
        records[platform] = {
            "version": version,
            "build": build,
            "filename": name,
            "bytes": record["bytes"],
            "sha256": record["sha256"],
            "url": ORIGIN + "/downloads/" + name,
        }
    manifest = {
        "schema": 1,
        "sha": claims["sha"],
        "version": version,
        "build": build,
        "run": run,
        "platforms": records,
    }
    if previous and run == previous.get("run"):
        if previous != manifest or any(
            (root / "current" / (p + ".xml")).read_bytes() != feeds[p] for p in PLATFORMS
        ):
            raise ValueError("published release is immutable")
        return previous
    # Validate every artifact and feed before making either platform discoverable.
    for record in records.values():
        destination = downloads / record["filename"]
        if destination.exists() and digest(destination) != record["sha256"]:
            raise ValueError("installer URL is immutable")
    releases = root / "releases"
    releases.mkdir(exist_ok=True)
    release = Path(tempfile.mkdtemp(prefix="release-", dir=releases))
    release.chmod(0o755)
    for platform, feed in feeds.items():
        (release / (platform + ".xml")).write_bytes(feed)
    (release / "releases.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    for record in records.values():
        source, destination = stage / record["filename"], downloads / record["filename"]
        if not destination.exists():
            source.chmod(0o644)
            os.link(source, destination)
        checksum = downloads / (record["filename"] + ".sha256")
        if not checksum.exists():
            with checksum.open("x") as output:
                output.write(record["sha256"] + "  " + record["filename"] + "\n")
    for path in release.iterdir():
        path.chmod(0o644)
    pointer = root / "next"
    pointer.unlink(missing_ok=True)
    pointer.symlink_to(release.relative_to(root), target_is_directory=True)
    os.replace(pointer, root / "current")
    return manifest


class Handler(BaseHTTPRequestHandler):
    verifier = None
    root, downloads = ROOT, DOWNLOADS

    def log_message(self, *_args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(120)

    def respond(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in {
            ENDPOINT + "/promote",
            *(ENDPOINT + "/artifact/" + p for p in PLATFORMS),
        }:
            self.respond(404, {"error": "not found"})
            return
        try:
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                raise ValueError("missing token")
            claims = self.verifier.verify(authorization[7:])
        except Exception:
            self.respond(401, {"error": "unauthorized"})
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("chunked upload is unsupported")
            length = int(self.headers["Content-Length"])
            if self.path == ENDPOINT + "/promote":
                if (
                    not 0 < length <= MAX_METADATA
                    or self.headers.get("Content-Type") != "application/json"
                ):
                    raise ValueError("metadata length/type")
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError("short metadata")
                result = promote(self.root, self.downloads, claims, json.loads(data))
            else:
                if self.headers.get("Content-Type") != "application/octet-stream":
                    raise ValueError("artifact type")
                result = upload(
                    self.root,
                    claims,
                    self.path.rsplit("/", 1)[1],
                    self.rfile,
                    length,
                    self.headers.get("X-Aira-SHA256", ""),
                )
        except (ValueError, TypeError, KeyError):
            self.respond(400, {"error": "invalid release; previous release retained"})
            return
        except Exception:
            self.respond(500, {"error": "publication failed; inspect current release receipt"})
            return
        self.respond(200, result)


def main():
    spec = importlib.util.spec_from_file_location("aira_oidc", "/opt/aira-site-deploy/server.py")
    oidc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oidc)
    Handler.verifier = oidc.Verifier(workflow=WORKFLOW, audience=ORIGIN + ENDPOINT)
    HTTPServer(("127.0.0.1", 8769), Handler).serve_forever()


if __name__ == "__main__":
    main()
