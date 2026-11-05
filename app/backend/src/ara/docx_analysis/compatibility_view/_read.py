"""Fresh compatibility proof and all-part validation precede logical view allocation."""

from ara.docx_analysis.compatibility import read_compatibility_catalog
from ara.docx_analysis.compatibility._models import Refused
from ara.docx_package import DocxLimits

from ._models import PROFILE, CompatibilityView
from ._project import project_part


def build_compatibility_view(data, *, source_sha256, limits=None):
    catalog = read_compatibility_catalog(data, source_sha256=source_sha256, limits=limits)
    if catalog.status == "blocked":
        return CompatibilityView(source_sha256, PROFILE, "blocked", catalog, (), catalog.issues)
    parts, issues, status = (), (), "ready"
    try:
        parts = tuple(project_part(data, p, source_sha256, DocxLimits()) for p in catalog.parts)
    except Refused as refusal:
        parts, issues, status = (), (refusal.issue,), "blocked"
    return CompatibilityView(source_sha256, PROFILE, status, catalog, parts, issues)
