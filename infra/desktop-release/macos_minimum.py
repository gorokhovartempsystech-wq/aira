"""Reject native dependencies whose deployment target exceeds declared macOS 14."""

import re
import subprocess
import sys
from pathlib import Path


def minimum(text):
    versions = []
    for block in text.split("Load command "):
        if "cmd LC_BUILD_VERSION\n" in block:
            platform = re.search(r"\bplatform\s+(\w+)", block)
            if platform and platform[1] not in {"1", "MACOS"}:
                continue
            match = re.search(r"\bminos\s+([0-9.]+)", block)
        elif "cmd LC_VERSION_MIN_MACOSX\n" in block:
            match = re.search(r"\bversion\s+([0-9.]+)", block)
        else:
            continue
        if match:
            parts = tuple(map(int, match[1].split(".")))
            versions.append((parts + (0, 0))[:3])
    return max(versions, default=(0, 0, 0))


def main():
    count = 0
    for path in Path(sys.argv[1]).rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic not in {
            b"\xcf\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf",
            b"\xca\xfe\xba\xbe",
            b"\xbe\xba\xfe\xca",
        }:
            continue
        result = subprocess.run(
            ["xcrun", "otool", "-l", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        if minimum(result.stdout) > (14, 0, 0):
            raise ValueError("Native dependency requires a newer macOS: " + path.name)
        count += 1
    if not count:
        raise ValueError("No native runtime files found")
    print(f"Checked macOS 14 deployment targets of {count} native runtime files.")


if __name__ == "__main__":
    main()
