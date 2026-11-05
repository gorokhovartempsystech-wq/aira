"""Explicit local editor registry; no global runtime or I/O on import."""

from ._commands import EditorCommand
from ._models import RegistryLimits
from ._registry import EditorRegistry

__all__ = ["EditorRegistry", "RegistryLimits", "EditorCommand"]
