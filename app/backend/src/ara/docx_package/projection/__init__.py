"""Read-only main-body structure, not Word rendering or an editable import.

The original validated package remains authoritative. Opaque nodes and coverage
notices must be considered before any future adapter uses this text for analysis.
No fields, revisions, links, styles or numbering are evaluated here.
"""

from .. import DocxLimits, open_docx
from ._models import DocxProjection, ProjectionError, ProjectionLimits, SourceAnchor
from ._parse import parse_main
from ._project import project_main

__all__ = ["project_docx", "ProjectionLimits", "ProjectionError", "SourceAnchor"]


def project_docx(
    data: bytes,
    *,
    limits: DocxLimits | None = None,
    projection_limits: ProjectionLimits | None = None,
) -> DocxProjection:
    """Project validated bytes in memory; package errors remain DocxError."""
    if projection_limits is None:
        projection_limits = ProjectionLimits()
    elif type(projection_limits) is not ProjectionLimits:
        raise ProjectionError("invalid_input")
    projection_limits.__post_init__()
    source = open_docx(data, limits=limits)
    root = parse_main(
        data, source, limits if limits is not None else DocxLimits(), projection_limits
    )
    return project_main(source, root)
