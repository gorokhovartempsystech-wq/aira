"""Build a local Apple Silicon pilot disk image from an explicitly staged runtime."""

import argparse
import base64
import json
import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def run(*args):
    subprocess.run(args, check=True, stdin=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--sparkle", required=True, type=Path, help="Verified Sparkle 2.10.1 distribution"
    )
    parser.add_argument("--version", default="0.2.5")
    parser.add_argument("--build", type=int, default=4)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version) or args.build < 3:
        parser.error("invalid release version/build")
    config = json.loads((Path(__file__).parents[1] / "updates/release-config.json").read_text())
    if len(base64.b64decode(config["public_key"], validate=True)) != 32:
        parser.error("invalid update verification key")
    framework = args.sparkle.resolve(strict=True) / "Sparkle.framework"
    if not framework.is_dir():
        parser.error("missing Sparkle.framework")
    source = args.payload.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or output.suffix != ".dmg":
        parser.error("output must be a new .dmg file")
    for relative in (
        "python/bin/python3.12",
        "pgsql/bin/postgres",
        "pgsql/bin/pg_ctl",
        "app/backend/ml_bundle/models/manifest.json",
        "app/frontend/static/index.html",
    ):
        if not (source / relative).is_file():
            parser.error(f"missing payload entry: {relative}")

    here = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="aira-macos-build-", dir="/private/tmp") as temp:
        work = Path(temp)
        volume = work / "volume"
        contents = volume / "AIRA.app/Contents"
        executable = contents / "MacOS/AIRA"
        executable.parent.mkdir(parents=True)
        payload = contents / "Resources/payload"
        payload.parent.mkdir()
        run("/usr/bin/ditto", str(source), str(payload))
        shutil.copy2(here / "serve.py", payload / "serve.py")
        (contents / "Resources/license-origin.txt").write_text(config["license_origin"] + "\n")
        (contents / "Frameworks").mkdir()
        run("/usr/bin/ditto", str(framework), str(contents / "Frameworks/Sparkle.framework"))
        shutil.copy2(here.parents[1] / "aira_host.py", payload / "app/frontend/aira_host.py")
        with (contents / "Info.plist").open("wb") as file:
            plistlib.dump(
                {
                    "CFBundleExecutable": "AIRA",
                    "CFBundleIdentifier": "org.aira.mac-pilot",
                    "CFBundleName": "AIRA",
                    "CFBundlePackageType": "APPL",
                    "CFBundleShortVersionString": args.version,
                    "CFBundleVersion": str(args.build),
                    "SUFeedURL": config["origin"] + "/updates/macos-arm64.xml",
                    "SUPublicEDKey": config["public_key"],
                    "SUEnableAutomaticChecks": True,
                    "SUAutomaticallyUpdate": True,
                    "SUEnableSystemProfiling": False,
                    "LSMinimumSystemVersion": "13.0",
                    "NSHighResolutionCapable": True,
                    "NSAppTransportSecurity": {
                        "NSAllowsLocalNetworking": True,
                        "NSExceptionDomains": {
                            "127.0.0.1": {"NSExceptionAllowsInsecureHTTPLoads": True},
                        },
                    },
                },
                file,
            )
        run(
            "/usr/bin/xcrun",
            "swiftc",
            "-target",
            "arm64-apple-macos13.0",
            "-module-cache-path",
            str(work / "module-cache"),
            "-O",
            "-F",
            str(args.sparkle.resolve()),
            "-framework",
            "Sparkle",
            "-Xlinker",
            "-rpath",
            "-Xlinker",
            "@executable_path/../Frameworks",
            str(here / "AIRA.swift"),
            "-o",
            str(executable),
        )
        run("/usr/bin/codesign", "--force", "--sign", "-", str(contents.parent))
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(contents.parent))
        (volume / "Applications").symlink_to("/Applications")
        output.parent.mkdir(parents=True, exist_ok=True)
        run(
            "/usr/bin/hdiutil",
            "create",
            "-volname",
            "AIRA Mac Pilot",
            "-srcfolder",
            str(volume),
            "-format",
            "UDZO",
            str(output),
        )
    print(output)


if __name__ == "__main__":
    main()
