"""Real model on the existing native guardian/lease/stop and publication path."""

import sys
from types import SimpleNamespace

from ara.docx_analysis.visible_word._models import PROFILE

from ..native_model import execution
from ._runtime_models import SupervisorError
from .runtime import _create_supervisor


def create_local_model_supervisor(
    *,
    settings,
    user_id,
    project_id,
    installation_id,
    root,
    model_key_provider=None,
    startup_checkpoint=None,
):
    if sys.platform == "darwin":
        from ._macos_adapter import MacPlatform as Parent
    elif sys.platform == "win32":
        from ._windows_adapter import WindowsPlatform as Parent
    else:
        raise SupervisorError("runtime_unavailable")

    protected = model_key_provider is not None
    if protected and not callable(model_key_provider):
        raise SupervisorError("runtime_unavailable")

    class WordPlatform(Parent):
        @staticmethod
        def _backend():
            backend = Parent._backend()

            def start(*args, **kwargs):
                if protected:
                    return backend.start(
                        *args, **kwargs, mode="protected_model", model_key=model_key_provider()
                    )
                return backend.start(*args, **kwargs, mode="local_model")

            return SimpleNamespace(
                clock_factory=backend.clock_factory,
                acquire_owner=backend.acquire_owner,
                start=start,
            )

    return _create_supervisor(
        settings=settings,
        user_id=user_id,
        project_id=project_id,
        installation_id=installation_id,
        root=root,
        execution=execution(
            **({"checkpoint": startup_checkpoint} if startup_checkpoint is not None else {})
        ),
        execution_kind="local_model",
        platform=WordPlatform(),
        source_profile=PROFILE,
    )
