"""Bind HTTP reads to issued desktop engines; placeholder URLs are not identities."""

from dataclasses import replace

from sqlalchemy.engine.base import OptionEngine

from ara.documents.runtime import DocumentRuntime

from ._models import DesktopDatabaseSettings, require


def bind_http_runtime(settings, runtime, registry_runtime, **scope):
    require(type(settings) is DesktopDatabaseSettings, "validation_error")
    settings.validate_scope(**scope)
    source = settings._source
    expected = source.document_runtime()
    for value, editor in ((runtime, False), (registry_runtime, True)):
        engine = getattr(value, "engine", None)
        matching_engine = engine is expected.engine or (
            editor
            and type(engine) is OptionEngine
            and engine._proxied is expected.engine
            and engine.pool is expected.engine.pool
        )
        require(
            type(value) is DocumentRuntime
            and matching_engine
            and (value.user_id, value.project_id, value.mode)
            == (expected.user_id, expected.project_id, expected.mode),
            "validation_error",
        )
    return replace(expected, engine=source._engine("analysis_read"))
