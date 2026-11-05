#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == "--documents" && "$#" == 1 ]]; then
  exec .venv/bin/python scripts/serve_documents.py
fi
if [[ "$#" != 0 ]]; then
  echo "Usage: bash scripts/dev.sh [--documents]" >&2
  exit 2
fi
exec .venv/bin/python -m uvicorn ara.app:create_app --factory --app-dir src --host 127.0.0.1 --port "${ARA_PORT:-8000}"
