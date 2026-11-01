"""In-memory DOCX history with source-relative selections; no UI or persistence."""

from ._models import (
    Caret,
    CaretTarget,
    EditorError,
    EditorSelection,
    EditorSnapshot,
    PasteLimits,
    SelectionTarget,
)
from ._session import EditorSession

__all__ = [
    "Caret",
    "CaretTarget",
    "EditorError",
    "EditorSelection",
    "EditorSnapshot",
    "PasteLimits",
    "SelectionTarget",
    "EditorSession",
]
