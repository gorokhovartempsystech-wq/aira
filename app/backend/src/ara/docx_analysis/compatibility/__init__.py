"""Original-source compatibility decisions for a fixed base Word capability profile."""

from ._models import (
    CompatibilityAction,
    CompatibilityCatalog,
    CompatibilityCatalogError,
    CompatibilityIssue,
    CompatibilityLimits,
    CompatibilityPart,
)
from ._read import read_compatibility_catalog

__all__ = [
    "CompatibilityAction",
    "CompatibilityCatalog",
    "CompatibilityCatalogError",
    "CompatibilityIssue",
    "CompatibilityLimits",
    "CompatibilityPart",
    "read_compatibility_catalog",
]
