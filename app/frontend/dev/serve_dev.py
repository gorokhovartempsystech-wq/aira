"""Local development stand for the AIRA frontend (Windows/macOS).

Builds the application through app/frontend/aira_host.py (the same composition as the
installed pilot build) and adds development extras: a fake licence endpoint and the
same-origin test pages under /aira/dev-pages/.

Analysis modes:
    --analysis fixture  explicit test analysis (no model weights needed, marked as fixture)
    --analysis model    real local model from app/backend/ml_bundle

Run from app/backend with the *base* Python 3.12 that has requirements.lock installed:
    python ..\\frontend\\dev\\serve_dev.py --runtime-root C:\\AIRA-dev-runtime \\
        --pg-port 15435 --initialize-test-database

On Windows do not use .venv\\Scripts\\python.exe: it is a redirecting launcher, and the
native analysis worker started through it exits without a result (adapter_error).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aira_host  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8017)
    parser.add_argument("--pg-port", type=int, default=15435)
    parser.add_argument("--analysis", choices=("fixture", "model"), default="fixture")
    parser.add_argument("--database", default="aira_native_test")
    parser.add_argument("--initialize-test-database", action="store_true")
    args = parser.parse_args()
    if not (1024 <= args.port <= 65535 and 1024 <= args.pg_port <= 65535):
        raise ValueError("Invalid local port")

    import uvicorn

    app = aira_host.build_app(
        database_url=f"postgresql+psycopg://postgres@127.0.0.1:{args.pg_port}/{args.database}",
        runtime_root=args.runtime_root, port=args.port, analysis=args.analysis,
        initialize=args.initialize_test_database, licence_stub=True, dev=True,
        dev_pages=Path(__file__).resolve().parent / "pages",
        on_ready=lambda: print(f"AIRA dev: http://127.0.0.1:{args.port}/aira/  (analysis={args.analysis})", flush=True),
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
