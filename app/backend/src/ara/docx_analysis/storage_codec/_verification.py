"""Private, synchronous review-local reuse of complete immutable record proofs."""

from contextlib import contextmanager
from contextvars import ContextVar
from threading import get_ident

_active = ContextVar("docx_review_verification", default=None)


@contextmanager
def verification_scope(records):
    # Strong references prevent identity reuse. Only the caller's already bounded
    # origin set is eligible; unrelated calls cannot grow this request's cache.
    state = [get_ident(), tuple(records), {}]
    token = _active.set(state)
    try:
        yield
    finally:
        state[1] = ()
        state[2].clear()
        _active.reset(token)


def restore_with_proof(restore, source, attempt, result, *, limits):
    state = _active.get()
    records = (source, attempt, result)
    eligible = (
        state is not None
        and state[0] == get_ident()
        and limits is None
        and any(all(a is b for a, b in zip(records, item, strict=True)) for item in state[1])
    )
    if not eligible:
        return restore(source, attempt, result, limits=limits)
    key = tuple(map(id, records))
    if key not in state[2]:
        # Store only after every original validation has succeeded.
        state[2][key] = restore(source, attempt, result, limits=limits)
    return state[2][key]
