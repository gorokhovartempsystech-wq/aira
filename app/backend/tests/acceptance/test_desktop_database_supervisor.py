"""Real native semantic fixture through owned Home/PG SQL, not developer settings."""

import json
import sys
from dataclasses import replace
from uuid import uuid4

import pytest
from test_desktop_database import bound
from test_docx_analysis_storage_codec import command
from test_docx_analysis_supervisor_runtime import finished, wait_for
from test_docx_review_v1 import fixture

from ara.docx_analysis.visible_main import build_visible_snapshot
from ara.docx_analysis_worker.supervisor.review_fixture import create_review_fixture_supervisor
from ara.docx_analysis_worker.supervisor.runtime import SupervisorError
from ara.docx_documents import get_docx, import_docx
from ara.docx_editor._models import SavedTarget

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native desktop fixture bridge")


def make(home, source, **changes):
    identity = home.identity()
    return create_review_fixture_supervisor(
        **(
            dict(
                settings=replace(source.settings()),
                user_id=identity.user_id,
                project_id=identity.project_id,
                installation_id=identity.installation_id,
                root=home.path("analysis"),
            )
            | changes
        )
    )


@pytest.mark.parametrize("wrong", ["user_id", "project_id", "installation_id", "root"])
def test_supervisor_scope_must_match_the_issued_database_source(tmp_path, wrong):
    with bound(tmp_path) as (home, _, _, source):
        value = (tmp_path / "elsewhere").resolve() if wrong == "root" else uuid4()
        with pytest.raises(SupervisorError) as caught:
            make(home, source, **{wrong: value})
        assert caught.value.code == "validation_error"
        assert source.view().connections == source.view().connecting == 0


def test_native_fixture_check_and_restart_preserve_exact_owned_docx(tmp_path):
    with bound(tmp_path) as (home, _, _, source):
        runtime = source.document_runtime()
        raw, _ = fixture()
        before = import_docx(
            runtime, document_id=uuid4(), title="Synthetic native fixture", data=raw
        )
        snapshot = build_visible_snapshot(
            before.current_data,
            document_id=before.document_id,
            storage_revision=before.storage_revision,
            source_sha256=before.current_sha256,
        )
        request = command(snapshot)
        target = SavedTarget(
            request.registry_id,
            request.document_id,
            request.session_id,
            request.save_command_id,
            request.command_sequence,
            request.session_revision,
            request.storage_revision,
            request.source_sha256,
            raw,
        )
        for count in (1, 2):
            supervisor = make(home, source)
            assert supervisor.view().phase == "new" and supervisor.view().fixture
            try:
                supervisor.start()
                wait_for(lambda: supervisor.view().phase == "ready")
                ticket = supervisor.admit_saved(
                    client_request_id=uuid4(), command=request, target_provider=lambda: target
                )
                result = finished(supervisor, ticket)
                assert result.sql_state.summary.status == "succeeded"
                assert result.sql_state.summary.execution_kind == "fixture"
            finally:
                assert supervisor.shutdown(timeout=5), supervisor.view()
            assert source.view().connections == source.view().connecting == 0
            assert get_docx(runtime, document_id=before.document_id) == before
            with runtime.engine.connect() as connection:
                rows = connection.exec_driver_sql(
                    "SELECT result_data FROM docx_analysis_results"
                ).all()
                assert len(rows) == count
                assert all(
                    json.loads(bytes(row[0]))["provenance"]["execution_kind"] == "fixture"
                    for row in rows
                )
