"""Original-address immutable XML view; not a content completeness/admission proof."""

from ._models import CompatibilityView, ViewNode, ViewPart
from ._read import build_compatibility_view

__all__ = ["CompatibilityView", "ViewNode", "ViewPart", "build_compatibility_view"]
