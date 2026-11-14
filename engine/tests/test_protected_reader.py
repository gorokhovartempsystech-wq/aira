"""Protected engine never hands an encrypted pathname to ONNX Runtime."""
import json

import pytest

from aira_ml import engine


def test_protected_model_is_loaded_from_authenticated_bytes(tmp_path, monkeypatch):
    class Tokenizer:
        def enable_truncation(self, *_): pass
        def enable_padding(self): pass

    class Session:
        def get_inputs(self): return []

    calls = []
    monkeypatch.setattr(engine.Tokenizer, 'from_file', lambda _: Tokenizer())
    monkeypatch.setattr(engine.ort, 'InferenceSession', lambda raw, options, **kw: calls.append((raw, kw)) or Session())
    expected = b'SYNTHETIC_AUTHENTICATED_MODEL'
    reads = []
    def reader(path):
        reads.append(path)
        return expected
    engine.Onnx(tmp_path, 2, model_reader=reader)
    assert reads == [tmp_path / 'model.int8.onnx']
    assert calls == [(expected, {'providers': ['CPUExecutionProvider']})]


def test_protected_manifest_never_falls_back_to_available_plaintext(tmp_path):
    (tmp_path / 'manifest.json').write_text(json.dumps({'protection': {'format': 'aira-model/1'}}))
    (tmp_path / 'model.int8.onnx').write_bytes(b'MUST_NOT_LOAD')
    with pytest.raises(ValueError, match='Protected model access required'):
        engine.Engine(tmp_path)
