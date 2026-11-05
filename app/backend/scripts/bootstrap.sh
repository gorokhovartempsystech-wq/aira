#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n "${ARA_PYTHON:-}" ]]; then
  ara_python="$ARA_PYTHON"
elif command -v python3.12 >/dev/null 2>&1; then
  ara_python="$(command -v python3.12)"
elif [[ -x "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" ]]; then
  ara_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
else
  echo "Python 3.12 is required. Set ARA_PYTHON to its executable." >&2
  exit 2
fi
"$ara_python" -c 'import sys; assert (3,12) <= sys.version_info[:2] < (3,14), "Python 3.12 or 3.13 is required"'
if [[ ! -x .venv/bin/python ]]; then
  "$ara_python" -m venv .venv
fi
if [[ -f requirements.lock ]]; then
  .venv/bin/python -m pip --isolated --disable-pip-version-check --no-cache-dir install --index-url https://pypi.org/simple -r requirements.lock
else
  .venv/bin/python - <<'PYDEPS'
import subprocess
import sys
import tomllib
from pathlib import Path
project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
dependencies = project["dependencies"] + project["optional-dependencies"]["dev"]
subprocess.run([sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-cache-dir", "install", "--index-url", "https://pypi.org/simple", *dependencies], check=True)
PYDEPS
fi
