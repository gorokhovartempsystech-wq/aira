"""Download pinned, checksum-verified official updater SDKs into a build folder."""

import argparse
import hashlib
import tarfile
import urllib.request
import zipfile
from pathlib import Path

SDK = {
    "macos": (
        "https://github.com/sparkle-project/Sparkle/releases/download/2.10.1/Sparkle-2.10.1.tar.xz",
        "1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27",
    ),
    "windows": (
        "https://github.com/vslavik/winsparkle/releases/download/v0.9.4/WinSparkle-0.9.4.zip",
        "6037df37fc263bd1650a1c4949681a9d40ffe991d01f35892a406cb5d103c976",
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=SDK)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        parser.error("destination must not exist")
    url, expected = SDK[args.platform]
    args.destination.mkdir(parents=True)
    archive = args.destination / url.rsplit("/", 1)[1]
    with urllib.request.urlopen(url, timeout=60) as response, archive.open("xb") as output:
        size = 0
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 100 * 1024 * 1024:
                raise ValueError("SDK exceeds expected size")
            output.write(chunk)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError("SDK checksum mismatch; archive was not extracted")
    if args.platform == "macos":
        with tarfile.open(archive) as bundle:
            bundle.extractall(args.destination, filter="data")
    else:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(args.destination)
    print("Verified SDK:", args.destination)


if __name__ == "__main__":
    main()
