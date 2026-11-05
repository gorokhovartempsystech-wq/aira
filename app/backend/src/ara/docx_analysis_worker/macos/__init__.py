"""Explicit Darwin clock and private lifetime locks; no model is started here."""

from ._clock import DarwinClock, ticks_to_ns
from ._errors import MacRuntimeError
from ._locks import RuntimeOwner, SlotLease, acquire_owner

__all__ = [
    "DarwinClock",
    "MacRuntimeError",
    "RuntimeOwner",
    "SlotLease",
    "acquire_owner",
    "ticks_to_ns",
]
