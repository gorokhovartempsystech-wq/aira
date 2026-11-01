#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ARA_DATABASE_URL:?Set ARA_DATABASE_URL for a prepared local PostgreSQL database}"
: "${ARA_MODELS_DIR:?Set ARA_MODELS_DIR to the local ONNX model pack}"
export ARA_ENVIRONMENT=local
export PYTHONPATH="$PWD/src:$PWD/../../engine${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -m uvicorn ara.local:create_local_app --factory --host 127.0.0.1 --port "${ARA_PORT:-8000}"
