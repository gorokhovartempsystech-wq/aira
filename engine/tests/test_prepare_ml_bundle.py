"""Bundle preparation validates before copying; models are synthetic byte fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / 'tools/prepare_ml_bundle.py'
spec = importlib.util.spec_from_file_location('prepare_ml_bundle', path)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


def source(tmp_path):
    models = tmp_path / 'models'
    models.mkdir()
    data = b'synthetic model bytes'
    (models / 'model.onnx').write_bytes(data)
    manifest = {'version': 'test', 'files': {'model.onnx': {
        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}}
    (models / 'manifest.json').write_text(json.dumps(manifest))
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    for name in bundle.RUNTIME_FILES:
        (runtime / name).write_text('# synthetic runtime')
    return models, runtime


def test_valid_bundle_includes_stable_nli_and_refuses_overwrite(tmp_path):
    models, runtime = source(tmp_path)
    dest = tmp_path / 'bundle'
    result = bundle.prepare(models, dest, engine_source=runtime)
    assert result['checked_model_files'] == 1
    assert (dest / 'aira_ml/stable_nli.py').is_file()
    before = (dest / 'models/model.onnx').read_bytes()
    with pytest.raises(ValueError):
        bundle.prepare(models, dest, engine_source=runtime)
    assert (dest / 'models/model.onnx').read_bytes() == before


def test_tampered_or_escaping_models_create_no_bundle(tmp_path):
    models, runtime = source(tmp_path)
    (models / 'model.onnx').write_bytes(b'bad')
    dest = tmp_path / 'bundle'
    with pytest.raises(ValueError):
        bundle.prepare(models, dest, engine_source=runtime)
    assert not dest.exists()
    manifest = {'version': 'test', 'files': {'../outside.onnx': {'bytes': 0, 'sha256': '0' * 64}}}
    (models / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        bundle.prepare(models, dest, engine_source=runtime)
    assert not dest.exists()
