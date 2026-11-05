"""Fixed new DTO policy; runtime trust still requires an original-source rebuild."""

from ara.docx_analysis.visible_style_lists._shape import validate as validate_lists

from ._models import PROFILE, STYLE_PROFILE, WordSnapshot


def validate(snapshot, limits):
    return validate_lists(
        snapshot, limits, snapshot_type=WordSnapshot, profile=PROFILE, style_profile=STYLE_PROFILE
    )
