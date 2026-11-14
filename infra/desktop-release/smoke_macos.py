"""Exercise the packaged ARM runtime twice without a real license key."""

import json
import plistlib
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    installer, version, build = sys.argv[1:]
    with tempfile.TemporaryDirectory(
        prefix="aira-release-smoke-", dir="/private/tmp"
    ) as temporary:
        root = Path(temporary)
        mount = root / "volume"
        mount.mkdir()
        subprocess.run(
            [
                "hdiutil",
                "attach",
                "-readonly",
                "-nobrowse",
                "-mountpoint",
                str(mount),
                installer,
            ],
            check=True,
        )
        try:
            app = mount / "AIRA.app"
            info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            assert info["CFBundleShortVersionString"] == version
            assert info["CFBundleVersion"] == build
            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(app)], check=True
            )
            payload = app / "Contents/Resources/payload"
            profile = root / "profile"
            for _ in range(2):
                with (root / "runtime.log").open("ab") as log:
                    child = subprocess.Popen(
                        [
                            str(payload / "python/bin/python3.12"),
                            "-I",
                            "-B",
                            "-u",
                            str(payload / "serve.py"),
                            str(profile),
                        ],
                        stdout=subprocess.PIPE,
                        stderr=log,
                        stdin=subprocess.DEVNULL,
                    )
                try:
                    reply = queue.Queue()

                    def handshake(process=child, response_queue=reply):
                        response_queue.put(process.stdout.read(4097))

                    reader = threading.Thread(target=handshake, daemon=True)
                    reader.start()
                    raw = reply.get(timeout=120)
                    assert 0 < len(raw) <= 4096
                    connection = json.loads(raw)
                    origin = connection["origin"]
                    request = Request(
                        origin + "/desktop/license",
                        headers={
                            "X-Aira-Session": connection["sessionToken"],
                            "Origin": origin,
                            "Referer": origin + "/aira/",
                        },
                    )
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline:
                        with urlopen(request, timeout=10) as response:
                            value = json.load(response)
                        if value["phase"] == "activation_required":
                            break
                        time.sleep(0.2)
                    else:
                        raise RuntimeError(
                            "Packaged runtime did not reach activation screen"
                        )
                    assert not list(profile.rglob("*.onnx"))
                finally:
                    if child.poll() is None:
                        child.send_signal(signal.SIGINT)
                    try:
                        code = child.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                        raise RuntimeError(
                            "Packaged runtime failed to stop cleanly"
                        ) from None
                    assert code == 0
            print(
                "Mac packaged runtime: two clean starts, "
                "activation gate and shutdown confirmed."
            )
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True)


if __name__ == "__main__":
    main()
