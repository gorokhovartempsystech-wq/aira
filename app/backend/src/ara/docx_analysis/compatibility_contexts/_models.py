"""Selected metadata only; ready never asserts text completeness or style usability."""

from dataclasses import dataclass, field

from ara.docx_analysis.compatibility_view import CompatibilityView
from ara.docx_analysis.notes import NoteCatalog
from ara.docx_analysis.sections import SectionCatalog
from ara.docx_analysis.table_styles import TableStyleCatalog
from ara.docx_analysis.visibility import StyleContext
from ara.docx_package import DocxSource
from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-compatibility/selected-contexts-v1"
STYLE_PROFILE = "docx-visibility/mc-styles-context-v1"
TABLE_PROFILE = "docx-table-styles/mc-neutrality-v1"
SECTION_PROFILE = "docx-sections/mc-current-references-v1"
NOTE_PROFILE = "docx-notes/mc-definitions-v1"


@dataclass(frozen=True, slots=True)
class CompatibilityContextIssue:
    code: str
    anchor: SourceAnchor | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class CompatibilityContexts:
    source_sha256: str
    profile: str
    status: str
    compatibility_sha256: str
    styles: StyleContext | None = field(repr=False)
    table_styles: TableStyleCatalog | None = field(repr=False)
    sections: SectionCatalog | None = field(repr=False)
    notes: NoteCatalog | None = field(repr=False)
    issues: tuple[CompatibilityContextIssue, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class Prepared:
    source: DocxSource = field(repr=False)
    view: CompatibilityView = field(repr=False)
    contexts: CompatibilityContexts = field(repr=False)


class Blocked(Exception):
    def __init__(self, code, anchor=None):
        self.issue = CompatibilityContextIssue(code, anchor)
        super().__init__(code)


def refuse_catalog(catalog, fallback):
    if catalog.status == "blocked":
        issue = catalog.issues[0] if catalog.issues else None
        raise Blocked(issue.code if issue else fallback, issue.anchor if issue else None)
