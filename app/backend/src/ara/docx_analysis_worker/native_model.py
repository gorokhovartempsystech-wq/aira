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


def run_native(request, emit, *, model_key=None):
    models, engine = bundle()
    # Native child uses isolated Python; only this installer-owned directory is added.
    sys.path.insert(0, str(engine))
    try:
        run(
            request,
            model_dir=models,
            engine_dir=engine,
            emit=emit,
            **({"model_key": model_key} if model_key is not None else {}),
        )
    finally:
        sys.path.remove(str(engine))
    return 0


def protected_configuration():
    from ara.model_protection.bundle import configuration

    models, _ = bundle()
    return configuration(models)
