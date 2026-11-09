"""Build a local Apple Silicon pilot disk image from an explicitly staged runtime."""

import argparse
import plistlib
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
    args = parser.parse_args()
    source = args.payload.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or output.suffix != ".dmg":
        parser.error("output must be a new .dmg file")
    for relative in (
        "python/bin/python3.12", "pgsql/bin/postgres", "pgsql/bin/pg_ctl",
        "app/backend/ml_bundle/models/manifest.json", "app/frontend/static/index.html",
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
        shutil.copy2(here.parents[1] / "aira_host.py", payload / "app/frontend/aira_host.py")
        with (contents / "Info.plist").open("wb") as file:
            plistlib.dump({
                "CFBundleExecutable": "AIRA",
                "CFBundleIdentifier": "org.aira.mac-pilot",
                "CFBundleName": "AIRA",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": "0.2.1",
                "CFBundleVersion": "1",
                "LSMinimumSystemVersion": "13.0",
                "NSHighResolutionCapable": True,
                "NSAppTransportSecurity": {
                    "NSAllowsLocalNetworking": True,
                    "NSExceptionDomains": {
                        "127.0.0.1": {"NSExceptionAllowsInsecureHTTPLoads": True},
                    },
                },
            }, file)
        run("/usr/bin/xcrun", "swiftc", "-target", "arm64-apple-macos13.0",
            "-module-cache-path", str(work / "module-cache"), "-O",
            str(here / "AIRA.swift"), "-o", str(executable))
        run("/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(contents.parent))
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(contents.parent))
        (volume / "Applications").symlink_to("/Applications")
        output.parent.mkdir(parents=True, exist_ok=True)
        run("/usr/bin/hdiutil", "create", "-volname", "AIRA Mac Pilot",
            "-srcfolder", str(volume), "-format", "UDZO", str(output))
    print(output)


if __name__ == "__main__":
    main()
