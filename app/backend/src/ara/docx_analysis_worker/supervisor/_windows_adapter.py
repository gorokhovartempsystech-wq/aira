"""Lazy Windows fixture wiring; HANDLE/I/O ownership remains with existing drivers."""

from types import SimpleNamespace

from .platform import _NativePlatform


def _backend():
    from ..windows import WindowsClock, acquire_owner
    from ..windows.driver import start_fixture_attempt

    return SimpleNamespace(
        clock_factory=WindowsClock, acquire_owner=acquire_owner, start=start_fixture_attempt
    )


class WindowsPlatform(_NativePlatform):
    @staticmethod
    def _backend():
        return _backend()

    @staticmethod
    def _physical(view):
        return bool(view.cleanup_confirmed)

    def acquire_owner(self, root):
        return super().acquire_owner(str(root))
