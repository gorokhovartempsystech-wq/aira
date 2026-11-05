"""Opt-in native fixture2 with outline saved admission and source-pinned retries."""

import sys
from functools import partial
from types import SimpleNamespace

from ara.docx_analysis.visible_outline._models import PROFILE

from ..structured_fixture import fixture_execution
from ._runtime_models import SupervisorError
from .runtime import _create_supervisor


def create_outline_fixture_supervisor(*, settings, user_id, project_id, installation_id, root):
    if sys.platform == "darwin":
        from ._macos_adapter import MacPlatform as Parent
    elif sys.platform == "win32":
        from ._windows_adapter import WindowsPlatform as Parent
    else:
        raise SupervisorError("runtime_unavailable")

    class OutlinePlatform(Parent):
        @staticmethod
        def _backend():
            backend = Parent._backend()
            return SimpleNamespace(
                clock_factory=backend.clock_factory,
                acquire_owner=backend.acquire_owner,
                start=partial(backend.start, mode="review2"),
            )

    return _create_supervisor(
        settings=settings,
        user_id=user_id,
        project_id=project_id,
        installation_id=installation_id,
        root=root,
        execution=fixture_execution(),
        platform=OutlinePlatform(),
        source_profile=PROFILE,
    )
