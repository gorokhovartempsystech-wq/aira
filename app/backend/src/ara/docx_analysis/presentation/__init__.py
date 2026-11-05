"""Pure source-verified review presentation. No persistence, inference or I/O."""

from ._view import FindingKey, Presentation, PresentationError, finding_keys, present

__all__ = ["FindingKey", "Presentation", "PresentationError", "finding_keys", "present"]
