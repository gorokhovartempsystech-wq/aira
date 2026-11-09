"""Fixed new DTO policy; runtime trust still requires an original-source rebuild."""

from ara.docx_analysis.visible_main._models import VisiblePiece
from ara.docx_analysis.visible_main._shape import Shape, require
from ara.docx_analysis.visible_style_lists._shape import validate as validate_lists

from ._models import PROFILE, STYLE_PROFILE, WordSnapshot


class WordShape(Shape):
    def value(self, value, expected, name="", owner=None):
        if owner is VisiblePiece and name == "kind":
            require(
                type(value) is str
                and value in {"text", "tab", "break", "nonbreaking_hyphen", "symbol"}
            )
            return
        return super().value(value, expected, name, owner)


def validate(snapshot, limits):
    return validate_lists(
        snapshot,
        limits,
        snapshot_type=WordSnapshot,
        profile=PROFILE,
        style_profile=STYLE_PROFILE,
        shape_type=WordShape,
    )
