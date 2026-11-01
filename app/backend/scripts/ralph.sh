#!/usr/bin/env bash
set -euo pipefail

project_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
codex_runtime="$project_root/.runtime/codex-cli/bin"

if [[ ! -x "$codex_runtime/codex" ]]; then
  printf '%s\n' 'Local Codex CLI is missing. See docs/cli-runtime.md.' >&2
  exit 127
fi
if [[ ! -x "$project_root/.venv/bin/python" ]]; then
  printf '%s\n' 'Project Python environment is missing. Follow README.md setup.' >&2
  exit 127
fi

# Select only the local CLI. Keep existing model, provider, authentication and policy.
export PATH="$codex_runtime:$PATH"
exec "$project_root/.venv/bin/python" "$project_root/scripts/ralph.py" "$@"
