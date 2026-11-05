"""Explicit owned macOS fixture backend; no GUI or real-model readiness implied."""

from ._models import DesktopError, DesktopView, FixtureConfig
from ._runtime import FixtureDesktop

__all__ = ["DesktopError", "DesktopView", "FixtureConfig", "FixtureDesktop"]
