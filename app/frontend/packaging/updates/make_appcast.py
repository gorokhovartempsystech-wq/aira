"""Sign an already tested installer and prepare its public Sparkle feed.

Does not upload or change the live channel. Reads the signing seed exclusively
from ~/secrets.env and pipes it to Sparkle, never via argv or a temporary file.
"""

import argparse
import base64
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from dotenv import dotenv_values

SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ET.register_namespace("sparkle", SPARKLE)


def appcast(*, platform, version, build, url, size, signature):
    if platform not in {"macos-arm64", "windows-x64"}:
        raise ValueError("unsupported platform")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or build < 1:
        raise ValueError("invalid version")
    if not url.startswith("https://") or size < 1:
        raise ValueError("invalid enclosure")
    if len(base64.b64decode(signature, validate=True)) != 64:
        raise ValueError("invalid signature")
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "AIRA updates"
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = "AIRA " + version
    attributes = {
        "url": url,
        "length": str(size),
        "type": "application/octet-stream",
        f"{{{SPARKLE}}}version": str(build) if platform == "macos-arm64" else version,
        f"{{{SPARKLE}}}shortVersionString": version,
        f"{{{SPARKLE}}}edSignature": signature,
    }
    if platform == "macos-arm64":
        ET.SubElement(item, f"{{{SPARKLE}}}minimumSystemVersion").text = "14.0"
    else:
        attributes[f"{{{SPARKLE}}}os"] = "windows-x64"
        # Inno uses its existing AppId/install directory and preserves LOCALAPPDATA.
        attributes[f"{{{SPARKLE}}}installerArguments"] = "/SILENT /NORESTART /AIRAUPDATE=1"
    ET.SubElement(item, "enclosure", attributes)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    parser.add_argument("--platform", choices=["macos-arm64", "windows-x64"], required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", type=int, required=True)
    parser.add_argument("--sign-update", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.installer.resolve(strict=True)
    expected = (
        f"AIRA-{args.version}-apple-silicon.dmg"
        if args.platform == "macos-arm64"
        else f"AIRA-Setup-{args.version}.exe"
    )
    if source.name != expected:
        parser.error("installer filename/version/platform mismatch")
    config = json.loads(Path(__file__).with_name("release-config.json").read_text())
    seed = dotenv_values(Path.home() / "secrets.env", interpolate=False).get(
        "AIRA_UPDATE_ED25519_SEED"
    )
    if not seed or len(base64.b64decode(seed, validate=True)) != 32:
        raise SystemExit("Missing or invalid release signing seed")
    # Reject a wrong key before publishing a release no installed app can verify.
    public_tool = args.sign_update.parent / "aira-public-key"
    public = subprocess.run(
        [str(public_tool)], input=seed, text=True, capture_output=True, check=True
    ).stdout.strip()
    if public != config["public_key"]:
        raise SystemExit("Release seed does not match the installed verification key")
    signature = subprocess.run(
        [str(args.sign_update), "--ed-key-file", "-", "-p", str(source)],
        input=seed,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    args.output.mkdir(parents=True, exist_ok=True)
    url = config["origin"].rstrip("/") + "/downloads/" + source.name
    xml = appcast(
        platform=args.platform,
        version=args.version,
        build=args.build,
        url=url,
        size=source.stat().st_size,
        signature=signature,
    )
    feed = args.output / (args.platform + ".xml")
    feed.write_bytes(xml)
    # Sparkle 2.10 also checks the feed's signature. Windows verifies the installer.
    if args.platform == "macos-arm64":
        subprocess.run(
            [str(args.sign_update), "--ed-key-file", "-", str(feed)],
            input=seed,
            text=True,
            capture_output=True,
            check=True,
        )
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (args.output / (source.name + ".sha256")).write_text(f"{digest}  {source.name}\n")
    print(f"Prepared {args.platform} {args.version}; upload installer before replacing feed.")


if __name__ == "__main__":
    main()

