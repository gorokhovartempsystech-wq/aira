#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing project environment; run bash scripts/bootstrap.sh first." >&2
  exit 2
fi
.venv/bin/python -m ruff check src tests scripts migrations
.venv/bin/python -m ruff format --check src tests scripts migrations
.venv/bin/python -m pytest -q
