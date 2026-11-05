"""Pure DOCX export for whole projected text spans; no structural or UI editing."""

from ._export import export_docx
from ._models import EditError, EditLimits, TextEdit

__all__ = ["TextEdit", "EditLimits", "EditError", "export_docx"]
