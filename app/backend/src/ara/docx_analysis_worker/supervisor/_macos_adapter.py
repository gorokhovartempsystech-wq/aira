"""Lazy macOS fixture wiring; no payload substitution or process adoption."""

from types import SimpleNamespace

from .platform import _NativePlatform


def _backend():
    from ..macos import DarwinClock, acquire_owner
    from ..macos.driver import start_fixture_attempt

    return SimpleNamespace(
        clock_factory=DarwinClock, acquire_owner=acquire_owner, start=start_fixture_attempt
    )


class MacPlatform(_NativePlatform):
    @staticmethod
    def _backend():
        return _backend()

    @staticmethod
    def _physical(view):
        return view.phase == "closed"
