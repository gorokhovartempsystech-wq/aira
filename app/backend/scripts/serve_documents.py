"""Explicit loopback launcher for the prepared, passwordless local ara_dev database."""

import hashlib
import os
import pwd
import sys
from pathlib import Path


def main() -> None:
    import uvicorn
    from sqlalchemy import URL

    root = Path(__file__).resolve().parents[1]
    if os.environ.get("ARA_ENVIRONMENT", "local") != "local":
        raise SystemExit("Document development server requires the local environment")
    try:
        port = int(os.environ.get("ARA_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit("ARA_PORT must be an integer between 1 and 65535") from None

    fingerprint = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    url = URL.create(
        "postgresql+psycopg",
        username=pwd.getpwuid(os.getuid()).pw_name,
        database="ara_dev",
        query={"host": f"/private/tmp/ara-pg-{os.getuid()}-{fingerprint}"},
    )
    # This opt-in command always uses the prepared local database, without credentials.
    # It does not start PostgreSQL, migrate schemas, or alter the parent environment.
    os.environ["ARA_ENVIRONMENT"] = "local"
    os.environ["ARA_DATABASE_URL"] = url.render_as_string(hide_password=False)
    sys.path.insert(0, str(root / "src"))
    uvicorn.run("ara.local:create_local_app", factory=True, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
