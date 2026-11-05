"""Explicit offline assembly from staged files; never execution or publication."""

from ._build import build_payload
from ._models import BuildError, BuildReceipt

__all__ = ["BuildError", "BuildReceipt", "build_payload"]
