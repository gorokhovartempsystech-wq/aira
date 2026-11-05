"""Stable inference contract without downloading models."""
from types import SimpleNamespace

import numpy as np
import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from aira_ml.stable_nli import StableNli


class FakeSession:
    def __init__(self):
        self.shapes = []

    def get_outputs(self):
        return [SimpleNamespace(shape=[None, 3])]

    def run(self, outputs, feed):
        ids = feed['input_ids']
        assert ids.shape[0] == 1
        assert np.all(feed['attention_mask'] == 1)
        self.shapes.append(ids.shape)
        # Neighbor-dependent behavior would be exposed by the single-row assertion.
        return [np.array([[ids.sum(), ids.shape[1], ids.max()]], dtype=np.float32)]


def model():
    tok = Tokenizer(WordLevel({'[UNK]': 0, '[PAD]': 1, 'a': 2, 'b': 3}, unk_token='[UNK]'))
    tok.pre_tokenizer = Whitespace()
    tok.enable_padding(pad_id=1, pad_token='[PAD]')
    session = FakeSession()
    old = SimpleNamespace(tok=tok, sess=session, names={'input_ids', 'attention_mask', 'token_type_ids'})
    return StableNli(old), old


def test_order_partition_and_neighbor_lengths_do_not_change_logits():
    nli, old = model()
    a, b = ['a', 'a b ' * 200, 'b'], ['b', 'b ' * 200, 'a b']
    expected = nli.run(a, b)
    assert np.array_equal(expected, nli.run(a, b, bs=1))
    assert np.array_equal(expected, nli.run(a[::-1], b[::-1])[::-1])
    assert np.array_equal(expected, np.concatenate([nli.run(a[:1], b[:1]), nli.run(a[1:], b[1:])]))
    for i, (premise, hypothesis) in enumerate(zip(a, b)):
        assert np.array_equal(expected[i], nli.run([premise], [hypothesis])[0])
    assert old.tok.padding is not None
    assert max(length for _, length in old.sess.shapes) <= 256


def test_empty_invalid_inputs_and_no_score_cache():
    nli, _ = model()
    assert nli.run([], []).shape == (0, 3)
    with pytest.raises(ValueError):
        nli.run(['a'], [])
    with pytest.raises(ValueError):
        nli.run(['a'], ['b'], bs=0)
    nli.run(['a'], ['b'])
    nli.run(['a'], ['b'])
    assert nli.calls == 2
