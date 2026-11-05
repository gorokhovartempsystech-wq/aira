#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${ARA_ENVIRONMENT:-local}" != "local" ]]; then
  echo "Fixture worker requires the local environment" >&2
  exit 2
fi
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing project environment" >&2
  exit 2
fi
exec .venv/bin/python scripts/serve_worker.py "$@"
