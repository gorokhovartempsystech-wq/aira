"""Sign tested CI artifacts with Sparkle, then publish through short-lived GitHub OIDC."""

import base64
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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

ENDPOINT = ORIGIN + "/_deploy/releases"


def token():
    request = Request(
        os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&" + urlencode({"audience": ENDPOINT}),
        headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]},
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)["value"]


def send(path, data, headers):
    request = Request(
        ENDPOINT + path,
        data=data,
        method="POST",
        headers={
            **headers,
            "Authorization": "Bearer " + token(),
        },
    )
    with urlopen(request, timeout=600) as response:
        return json.load(response)


def main():
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get(
        "GITHUB_EVENT_NAME"
    ) not in {"push", "workflow_dispatch"}:
        raise SystemExit("Only main may sign and publish desktop updates")
    work = Path(os.environ["RUNNER_TEMP"]) / "aira-release-sign"
    work.mkdir()
    seed = os.environ.pop("AIRA_UPDATE_ED25519_SEED", "")
    if not seed:
        raise SystemExit(
            "Missing repository secret AIRA_UPDATE_ED25519_SEED; previous release retained"
        )
    home_secret = Path.home() / "secrets.env"
    if home_secret.exists():
        raise SystemExit("Refusing to replace an existing runner ~/secrets.env")
    if len(base64.b64decode(seed, validate=True)) != 32:
        raise ValueError("invalid signing key")
    home_secret.touch(mode=0o600)
    home_secret.write_text("AIRA_UPDATE_ED25519_SEED='" + seed + "'\n")
    del seed
    try:
        subprocess.run(
            [
                sys.executable,
                "app/frontend/packaging/updates/fetch_sdk.py",
                "macos",
                str(work / "sparkle"),
            ],
            check=True,
        )
        signer = work / "sparkle/bin/sign_update"
        subprocess.run(
            [
                "xcrun",
                "swiftc",
                "app/frontend/packaging/updates/public-key.swift",
                "-o",
                str(signer.parent / "aira-public-key"),
            ],
            check=True,
        )
        artifacts = Path("release-artifacts")
        version = version_for_run(os.environ["GITHUB_RUN_NUMBER"])
        build = build_for_run(os.environ["GITHUB_RUN_NUMBER"])
        metadata = {
            "sha": os.environ["GITHUB_SHA"],
            "version": version,
            "build": build,
            "platforms": {},
            "feeds": {},
        }
        for platform in PLATFORMS:
            source = artifacts / platform / filename(platform, version)
            receipt = json.loads((artifacts / platform / (platform + ".json")).read_text())
            expected = {
                "platform": platform,
                "sha": metadata["sha"],
                "version": version,
                "build": build,
                "filename": source.name,
                "bytes": source.stat().st_size,
                "sha256": digest(source),
            }
            if receipt != expected:
                raise ValueError("tested artifact receipt does not match this checkout")
            subprocess.run(
                [
                    sys.executable,
                    "app/frontend/packaging/updates/make_appcast.py",
                    str(source),
                    "--platform",
                    platform,
                    "--version",
                    version,
                    "--build",
                    str(build),
                    "--minimum-system-version",
                    "14.0",
                    "--sign-update",
                    str(signer),
                    "--output",
                    str(work / "updates"),
                ],
                check=True,
            )
            feed = (work / "updates" / (platform + ".xml")).read_bytes()
            enclosure = ET.fromstring(feed).find("channel/item/enclosure")
            # Use only the public key for independent verification, never Keychain.
            import mmap

            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            with (
                source.open("rb") as stream,
                mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data,
            ):
                Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY)).verify(
                    base64.b64decode(enclosure.attrib["{" + SPARKLE + "}edSignature"]), data
                )
            metadata["platforms"][platform] = expected
            metadata["feeds"][platform] = base64.b64encode(feed).decode()
        for platform in PLATFORMS:
            record = metadata["platforms"][platform]
            source = artifacts / platform / record["filename"]
            with source.open("rb") as stream:
                send(
                    "/artifact/" + platform,
                    stream,
                    {
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(record["bytes"]),
                        "X-Aira-SHA256": record["sha256"],
                    },
                )
        receipt = send(
            "/promote", json.dumps(metadata).encode(), {"Content-Type": "application/json"}
        )
        if receipt["sha"] != metadata["sha"] or receipt["version"] != version:
            raise ValueError("promotion receipt mismatch")
        with urlopen(ORIGIN + "/updates/releases.json", timeout=20) as response:
            public = json.load(response)
        if public != receipt:
            raise ValueError("public release manifest mismatch")
        for platform in PLATFORMS:
            record = receipt["platforms"][platform]
            with urlopen(Request(record["url"], method="HEAD"), timeout=20) as response:
                if int(response.headers["Content-Length"]) != record["bytes"]:
                    raise ValueError("public installer size mismatch")
            with urlopen(ORIGIN + "/updates/" + platform + ".xml", timeout=20) as response:
                if response.read() != base64.b64decode(metadata["feeds"][platform]):
                    raise ValueError("public update feed mismatch")
        print("Published signed Windows and Mac " + version + " from " + metadata["sha"])
    finally:
        home_secret.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("Desktop publication failed: " + type(error).__name__) from None
