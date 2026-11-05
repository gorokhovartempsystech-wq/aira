"""Scoped effective visibility without writes, inference or HTTP installation."""

from ._load import get_resolution
from ._models import FindingAlias, Resolution, ResolutionLimits

__all__ = ["FindingAlias", "Resolution", "ResolutionLimits", "get_resolution"]
