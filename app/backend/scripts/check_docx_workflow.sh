#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing project environment: run bash scripts/bootstrap.sh first." >&2
  exit 2
fi
.venv/bin/python - <<'PY'
import sys
from pathlib import Path
if sys.platform != 'darwin':
    raise SystemExit('This owned workflow currently requires macOS; Windows-native gate remains open.')
if not Path('.runtime/Postgres.app/Contents/Versions/18/bin/postgres').is_file():
    raise SystemExit('Missing project-local Postgres.app 18 runtime; see docs/docx-workflow-handoff.md.')
PY
mkdir -p .runtime/aira-workflow-demo
AIRA_WORKFLOW_OUTPUT="$(mktemp -d "$PWD/.runtime/aira-workflow-demo/run-XXXXXX")"
export AIRA_WORKFLOW_OUTPUT
.venv/bin/python -m pytest -q tests/acceptance/test_docx_client_workflow.py
printf '\nSynthetic DOCX and report: %s\n' "$AIRA_WORKFLOW_OUTPUT"
