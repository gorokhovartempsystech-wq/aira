"""Encode once without truncation; send only those checked IDs to inference."""

from dataclasses import dataclass, field

from ._errors import ModelInputError, require


@dataclass(frozen=True, slots=True, repr=False)
class TokenBatch:
    input_ids: tuple[tuple[int, ...], ...] = field(repr=False)
    attention_mask: tuple[tuple[int, ...], ...] = field(repr=False)
    token_type_ids: tuple[tuple[int, ...], ...] = field(repr=False)

    def __repr__(self):
        return "<TokenBatch>"


def _inputs(left, right, batch_size):
    require(type(batch_size) is int and 1 <= batch_size <= 32, "invalid_input")
    require(type(left) in (list, tuple) and len(left) <= 4096, "invalid_input")
    require(
        right is None or type(right) in (list, tuple) and len(right) == len(left), "invalid_input"
    )
    count = 0
    for values in (left,) if right is None else (left, right):
        for s in values:
            require(type(s) is str, "invalid_input")
            count += len(s)
            require(count <= 2000000, "invalid_input")
            try:
                s.encode("utf-8")
            except UnicodeError:
                raise ModelInputError("invalid_input") from None
    return list(left) if right is None else list(zip(left, right))


def _integer(value):
    return type(value) is int and 0 <= value < 2**31


def _encodings(tokenizer, rows, batch_size):
    tokenizer.no_truncation()
    tokenizer.no_padding()
    require(tokenizer.truncation is None and tokenizer.padding is None)
    pad = tokenizer.token_to_id("[PAD]")
    require(_integer(pad))
    values = tokenizer.encode_batch(rows, add_special_tokens=True)
    require(tokenizer.truncation is None and tokenizer.padding is None)
    require(type(values) in (list, tuple) and len(values) == len(rows))
    checked = []
    for item in values:
        ids, mask, types, overflow = item.ids, item.attention_mask, item.type_ids, item.overflowing
        require(all(type(v) in (list, tuple) for v in (ids, mask, types, overflow)))
        require(len(ids) > 0 and len(ids) == len(mask) == len(types) and not overflow)
        require(all(_integer(v) for v in ids) and all(_integer(v) for v in types))
        require(all(type(v) is int and v == 1 for v in mask))
        require(len(ids) <= 256, "model_input_limit_exceeded")
        checked.append((tuple(ids), tuple(mask), tuple(types)))
    batches = []
    for offset in range(0, len(checked), batch_size):
        group = checked[offset : offset + batch_size]
        width = max(len(row[0]) for row in group)
        fields = []
        for index, padding in ((0, pad), (1, 0), (2, 0)):
            fields.append(
                tuple(row[index] + (padding,) * (width - len(row[index])) for row in group)
            )
        batches.append(TokenBatch(*fields))
    return tuple(batches)


def encode_batches(tokenizer, left, right=None, *, batch_size=32):
    rows = _inputs(left, right, batch_size)
    if not rows:
        return ()
    try:
        return _encodings(tokenizer, rows, batch_size)
    except ModelInputError:
        raise
    except Exception:
        raise ModelInputError("model_unavailable") from None


def run_guarded(tokenizer, infer_batch, concatenate, left, right=None, *, batch_size=32):
    batches = encode_batches(tokenizer, left, right, batch_size=batch_size)
    try:
        return concatenate(tuple(infer_batch(batch) for batch in batches))
    except Exception:
        raise ModelInputError("adapter_error") from None
