"""C2 actual encodings are passed through; tokenizer doubles are synthetic only."""

from types import SimpleNamespace

import pytest
from test_docx_model_pack import api, reject


class Tokenizer:
    def __init__(self, lengths=(3, 5)):
        self.lengths = lengths
        self.truncation = {"max_length": 2}
        self.padding = {"length": 2}
        self.calls = []
        self.modify = lambda x: None

    def no_truncation(self):
        self.truncation = None

    def no_padding(self):
        self.padding = None

    def token_to_id(self, text):
        assert text == "[PAD]"
        return 99

    def encode_batch(self, rows, *, add_special_tokens):
        assert self.truncation is None and self.padding is None
        assert add_special_tokens is True
        self.calls.append(tuple(rows))
        out = [
            SimpleNamespace(
                ids=list(range(n)), attention_mask=[1] * n, type_ids=[0] * n, overflowing=[]
            )
            for n in self.lengths
        ]
        self.modify(out)
        return out


def test_whitespace_unicode_pair_directions_and_exact_batch_padding():
    tok = Tokenizer((3, 5, 2))
    left, right = ["  я😀\n", "b", "c"], ["b", "  я😀\n", "d"]
    out = api().encode_batches(tok, left, right, batch_size=2)
    assert tok.calls == [(("  я😀\n", "b"), ("b", "  я😀\n"), ("c", "d"))]
    assert len(out) == 2
    assert out[0].input_ids == ((0, 1, 2, 99, 99), (0, 1, 2, 3, 4))
    assert out[0].attention_mask == ((1, 1, 1, 0, 0), (1, 1, 1, 1, 1))
    assert out[0].token_type_ids == ((0,) * 5, (0,) * 5)
    assert out[1].input_ids == ((0, 1),)


def test_inference_receives_checked_encodings_without_second_tokenization():
    tok, calls = Tokenizer(), []

    def infer(batch):
        calls.append(batch)
        return len(batch.input_ids)

    result = api().run_guarded(tok, infer, tuple, ["a", "b"], batch_size=1)
    assert result == (1, 1) and len(tok.calls) == 1
    assert [c.input_ids for c in calls] == [((0, 1, 2),), ((0, 1, 2, 3, 4),)]


@pytest.mark.parametrize("length", [256, 257])
def test_specials_included_at_256_boundary(length):
    tok, calls = Tokenizer((length,)), []

    def invoke():
        return api().run_guarded(tok, lambda b: calls.append(b), tuple, ["short"])

    if length == 256:
        assert invoke() == (None,) and len(calls[0].input_ids[0]) == 256
    else:
        reject(invoke, "model_input_limit_exceeded")
        assert calls == []


def test_tail_overflow_prevents_any_inference_even_with_small_batch():
    tok, calls = Tokenizer((3, 257)), []
    reject(
        lambda: api().run_guarded(tok, calls.append, tuple, ["a", "b"], batch_size=1),
        "model_input_limit_exceeded",
    )
    assert calls == []


@pytest.mark.parametrize(
    "left,right,bs",
    [
        (["a"], [], 1),
        (["a"], ["b", "c"], 1),
        ("a", None, 1),
        ([1], None, 1),
        (["a"], None, True),
        (["a"], None, 0),
        (["a"], None, 33),
        (["a"] * 4097, None, 1),
        (["a" * 2000001], None, 1),
        (["\ud800"], None, 1),
    ],
)
def test_bad_input_is_rejected_before_tokenization(left, right, bs):
    tok = Tokenizer()
    reject(lambda: api().encode_batches(tok, left, right, batch_size=bs), "invalid_input")
    assert tok.calls == []


@pytest.mark.parametrize(
    "fault",
    ["ids_bool", "ids_negative", "ids_large", "mask", "types", "overflow", "count", "empty"],
)
def test_malformed_encoding_cannot_reach_inference(fault):
    tok, calls = Tokenizer(), []

    def mutate(out):
        if fault == "ids_bool":
            out[0].ids[0] = True
        if fault == "ids_negative":
            out[0].ids[0] = -1
        if fault == "ids_large":
            out[0].ids[0] = 2**31
        if fault == "mask":
            out[0].attention_mask[0] = 0
        if fault == "types":
            out[0].type_ids.pop()
        if fault == "overflow":
            out[0].overflowing = [object()]
        if fault == "count":
            out.pop()
        if fault == "empty":
            out[0].ids = []

    tok.modify = mutate
    reject(lambda: api().run_guarded(tok, calls.append, tuple, ["a", "b"]))
    assert calls == []


@pytest.mark.parametrize("when", ["before", "after"])
def test_truncation_cannot_remain_or_be_reenabled(when):
    tok = Tokenizer()
    if when == "before":
        tok.no_truncation = lambda: None
    else:
        tok.modify = lambda _: setattr(tok, "truncation", {"max_length": 2})
    reject(lambda: api().encode_batches(tok, ["a", "b"]))


def test_empty_input_never_calls_tokenizer_or_inference():
    assert api().run_guarded(None, None, tuple, []) == ()


@pytest.mark.parametrize("where", ["tokenizer", "inference", "concatenate"])
def test_private_exceptions_are_sanitized(where):
    tok = Tokenizer()

    def broken(*a, **k):
        raise RuntimeError("PRIVATE input text")

    if where == "tokenizer":
        tok.encode_batch = broken
    reject(
        lambda: api().run_guarded(
            tok,
            broken if where == "inference" else lambda b: b,
            broken if where == "concatenate" else tuple,
            ["a", "b"],
        ),
        "model_unavailable" if where == "tokenizer" else "adapter_error",
    )
