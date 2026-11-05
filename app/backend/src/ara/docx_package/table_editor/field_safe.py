"""Opt-in editor: protect complete field blocks, edit only other supported blocks."""

from ..projection import ProjectionLimits
from ._session import TableEditorSession


class FieldSafeTableEditorSession(TableEditorSession):
    def __init__(self, data, **kwargs):
        kwargs.setdefault("projection_limits", ProjectionLimits(isolate_complex_fields=True))
        super().__init__(data, **kwargs)

    @classmethod
    def restore(cls, data, **kwargs):
        kwargs.setdefault("projection_limits", ProjectionLimits(isolate_complex_fields=True))
        return super().restore(data, **kwargs)
