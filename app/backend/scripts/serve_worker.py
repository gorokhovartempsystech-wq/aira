"""Opt-in worker on the prepared passwordless local ara_dev database."""

import hashlib
import os
import pwd
import sys
from pathlib import Path


def main():
    from sqlalchemy import URL

    root = Path(__file__).resolve().parents[1]
    if os.environ.get("ARA_ENVIRONMENT", "local") != "local":
        raise SystemExit("Fixture worker requires the local environment")
    fingerprint = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    url = URL.create(
        "postgresql+psycopg",
        username=pwd.getpwuid(os.getuid()).pw_name,
        database="ara_dev",
        query={"host": f"/private/tmp/ara-pg-{os.getuid()}-{fingerprint}"},
    )
    os.environ["ARA_ENVIRONMENT"] = "local"
    os.environ["ARA_DATABASE_URL"] = url.render_as_string(hide_password=False)
    sys.path.insert(0, str(root / "src"))
    from ara.worker.__main__ import main as worker_main

    return worker_main()


if __name__ == "__main__":
    raise SystemExit(main())
