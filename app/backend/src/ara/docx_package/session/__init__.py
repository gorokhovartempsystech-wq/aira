"""Bounded DOCX editing sessions with exact undo/redo, entirely in memory.

This layer supplies no UI, disk storage, autosave or crash recovery. Editing and
projection retain the restrictions of the existing range, structure, formatting
and paragraph-boundary package APIs.
"""

from ._models import SessionError, SessionLimits, SessionSnapshot
from ._session import DocxSession

__all__ = ["SessionLimits", "SessionSnapshot", "SessionError", "DocxSession"]
