"""Pure source-relative text ranges within existing DOCX paragraphs."""

from ._export import export_docx_ranges
from ._models import RangeEdit, RangeError, RangeLimits, TextPosition

__all__ = ["TextPosition", "RangeEdit", "RangeLimits", "RangeError", "export_docx_ranges"]
