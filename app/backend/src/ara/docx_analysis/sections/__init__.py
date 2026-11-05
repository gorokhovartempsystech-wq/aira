"""Pure current section definitions; not a document-text or pagination claim."""

from ._models import (
    Section,
    SectionBinding,
    SectionCatalog,
    SectionCatalogError,
    SectionHistory,
    SectionIssue,
    SectionLimits,
    SectionReference,
    SectionStory,
)
from ._read import read_section_catalog

__all__ = [
    "Section",
    "SectionBinding",
    "SectionCatalog",
    "SectionCatalogError",
    "SectionHistory",
    "SectionIssue",
    "SectionLimits",
    "SectionReference",
    "SectionStory",
    "read_section_catalog",
]
