"""Original note definitions; visible reference resolution is a separate capability."""

from ._models import NoteCatalog, NoteCatalogError, NoteDefinition, NoteIssue, NoteLimits, NotePart
from ._read import read_note_catalog

__all__ = [
    "NoteCatalog",
    "NoteCatalogError",
    "NoteDefinition",
    "NoteIssue",
    "NoteLimits",
    "NotePart",
    "read_note_catalog",
]
