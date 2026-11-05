"""Real model from an installer-owned fixed bundle, never document-supplied paths."""

import sys
from pathlib import Path

from .local_model import package_identity, run


def bundle():
    root = Path(__file__).resolve().parents[3] / "ml_bundle"
    return root / "models", root


def execution():
    models, engine = bundle()
    return package_identity(models, engine)


def run_native(request, emit):
    models, engine = bundle()
    # Native child uses isolated Python; only this installer-owned directory is added.
    sys.path.insert(0, str(engine))
    try:
        run(request, model_dir=models, engine_dir=engine, emit=emit)
    finally:
        sys.path.remove(str(engine))
    return 0
