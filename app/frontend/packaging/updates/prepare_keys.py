"""Create a release seed in ~/secrets.env; export only its public verification key."""

import argparse
import base64
import fcntl
import os
import secrets
import subprocess
from pathlib import Path

from dotenv import dotenv_values

KEY = "AIRA_UPDATE_ED25519_SEED"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-key-tool", required=True, type=Path)
    args = parser.parse_args()
    path = Path.home() / "secrets.env"
    # Append under a lock; never replace or print unrelated settings.
    with path.open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        values = dotenv_values(path, interpolate=False)
        seed = values.get(KEY)
        if not seed:
            seed = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
            os.fchmod(stream.fileno(), 0o600)
            stream.write(f"\n{KEY}={seed}\n")
            stream.flush()
            os.fsync(stream.fileno())
        if len(base64.b64decode(seed, validate=True)) != 32:
            raise SystemExit("Invalid release seed; no keys were changed.")
    result = subprocess.run(
        [str(args.public_key_tool.resolve(strict=True))],
        input=seed,
        text=True,
        capture_output=True,
        check=True,
    )
    public = result.stdout.strip()
    if len(base64.b64decode(public, validate=True)) != 32:
        raise SystemExit("Invalid public verification key")
    print(public)


if __name__ == "__main__":
    main()
