"""Exact DOCX persistence; no UI, autosave scheduler or analysis recovery."""

from ._dto import DocxSummary, StoredDocx
from .storage import get_docx, import_docx, list_docx, save_docx

__all__ = ["StoredDocx", "DocxSummary", "import_docx", "get_docx", "list_docx", "save_docx"]
