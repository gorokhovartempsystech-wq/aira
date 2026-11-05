"""Explicit local review preference storage; no implicit configuration or migration."""

from ._commands import set_hidden, set_preferences
from ._models import PreferenceReceipt, PreferencesState
from ._reads import get_state

__all__ = ["PreferenceReceipt", "PreferencesState", "get_state", "set_hidden", "set_preferences"]
