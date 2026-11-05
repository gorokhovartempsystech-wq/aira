"""HTTP analysis must bind issued engines, never compare placeholder URLs."""

import sys
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from test_desktop_database import bound
from test_desktop_database_supervisor import make

from ara.app import create_app
from ara.config import ConfigurationError
from ara.desktop.database import DatabaseError

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native desktop binding")


def test_desktop_http_reads_share_owned_database_but_have_separate_bounded_lane(tmp_path):
    with bound(tmp_path) as (home, _, _, source):
        runtime = source.document_runtime()
        supervisor = make(home, source)
        app = create_app(document_runtime=runtime, analysis_supervisor=supervisor)
        service = app.state.docx_analysis_service
        assert service.runtime.engine is not runtime.engine
        assert source.view().connections == source.view().connecting == 0
        one = service.runtime.engine.connect()
        two = service.runtime.engine.connect()
        try:
            assert one.exec_driver_sql("SHOW statement_timeout").scalar_one() == "2s"
            assert one.exec_driver_sql("SHOW lock_timeout").scalar_one() == "500ms"
            assert one.exec_driver_sql("SHOW transaction_timeout").scalar_one() == "5s"
            assert (
                one.exec_driver_sql("SELECT id FROM users").scalar_one() == home.identity().user_id
            )
            with pytest.raises(DatabaseError) as caught:
                service.runtime.engine.connect()
            assert caught.value.code == "database_busy"
            assert not source.shutdown(0)
            assert source.view().connections == 2
            with pytest.raises(DatabaseError):
                service.runtime.engine.connect()
            one.rollback()
            two.rollback()
        finally:
            one.close()
            two.close()
            service.close()
        assert source.shutdown(0) and not source.view().resources_pending


@pytest.mark.parametrize("wrong", ["engine", "user_id", "project_id", "registry_engine"])
def test_equal_url_cannot_substitute_foreign_runtime_or_registry(tmp_path, wrong):
    from ara.docx_analysis_api._service import Service
    from ara.docx_editor import EditorRegistry

    with bound(tmp_path) as (home, _, _, source):
        runtime = source.document_runtime()
        supervisor = make(home, source)
        foreign = create_engine(runtime.engine.url)
        try:
            changed = (
                replace(runtime, **{wrong: uuid4()})
                if wrong in ("user_id", "project_id")
                else replace(runtime, engine=foreign)
            )
            registry = EditorRegistry(changed if wrong == "registry_engine" else runtime)
            with pytest.raises(ConfigurationError):
                Service(runtime if wrong == "registry_engine" else changed, registry, supervisor)
            assert source.view().connections == source.view().connecting == 0
        finally:
            foreign.dispose()
