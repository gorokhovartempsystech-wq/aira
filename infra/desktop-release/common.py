"""Public release policy shared by build runners and the bounded publisher."""

import hashlib
import re
import sys
from pathlib import Path
from urllib.request import urlopen

ORIGIN = "https://51.250.81.70"
PUBLIC_KEY = "1zLepAlzB1jBqkgj68TJgYYVgoGvLhA2U56fD68w/+4="
PLATFORMS = ("windows-x64", "macos-arm64")
PINS = {
    "models": (
        "aira-models-0.2m-protected-1.zip",
        "7d4f227bd8f9edab1bbcbbddc199be8abeb5abd5b3b4329f717e5d041606ba4e",
    ),
    "windows-runtime": (
        "AIRA-Setup-0.2.0.exe",
        "01717fdeadcdb2ea5aa057e9e4330a2b6941167d962686ec5a439e549771a9fa",
    ),
    "macos-runtime": (
        "AIRA-0.2.7-apple-silicon.dmg",
        "27a7d1bd4490c38770b9cff68ed4b1e02967487db13729785779107b110523ef",
    ),
}
SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def version_for_run(number):
    if not re.fullmatch(r"[1-9][0-9]{0,4}", str(number)) or int(number) > 65535:
        raise ValueError("invalid release run number")
    return "0.3." + str(int(number))


def build_for_run(number):
    version_for_run(number)
    return 1000000 + int(number)


def filename(platform, version):
    if platform not in PLATFORMS or not re.fullmatch(r"0\.3\.[1-9][0-9]{0,4}", version):
        raise ValueError("invalid platform/version")
    return (
        "AIRA-Setup-" + version + ".exe"
        if platform == "windows-x64"
        else "AIRA-" + version + "-apple-silicon.dmg"
    )


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download_pin(kind, destination):
    name, expected = PINS[kind]
    target = Path(destination) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if digest(target) != expected:
            raise ValueError("transferred build input checksum mismatch")
        print("Verified transferred build input " + name, flush=True)
        return target
    print("Downloading pinned build input " + name, flush=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    try:
        with urlopen(ORIGIN + "/downloads/" + name, timeout=600) as response:
            if response.geturl() != ORIGIN + "/downloads/" + name:
                raise ValueError("unexpected download redirect")
            with temporary.open("xb") as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 2 * 1024**3:
                        raise ValueError("download too large")
                    output.write(chunk)
        if digest(temporary) != expected:
            raise ValueError("pinned runtime checksum mismatch")
        temporary.replace(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def require_source(root):
    root = Path(root)
    required = [
        "app/backend/src/ara/model_protection/integration.py",
        "app/backend/src/ara/model_protection/bundle.py",
        "app/frontend/packaging/windows/aira_startup.py",
        "app/frontend/packaging/windows/aira_licensed_app.py",
        "tools/smoke_windows_desktop.py",
    ]
    if any(not (root / name).is_file() for name in required):
        raise ValueError("merge the reviewed desktop integration before releasing main")


def verify_models(models):
    """Validate the actual bundle using the same decoder as the shipped runtime."""
    sys.path.insert(0, str(Path("app/backend/src").resolve()))
    from ara.model_protection.bundle import configuration

    if configuration(models) is None or list(Path(models).rglob("*.onnx")):
        raise ValueError("a valid protected model bundle is required")
