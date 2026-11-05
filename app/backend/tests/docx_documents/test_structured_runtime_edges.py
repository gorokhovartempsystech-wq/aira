"""Structured process admission keeps closed host modes, scopes and failure boundaries."""

import importlib
import sys
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_analysis_runs_start import counts, finish, reject
from test_docx_analysis_runs_start import world as world
from test_docx_structured_fixture import api as fixture_api
from test_docx_structured_fixture import prepared
from test_docx_structured_runtime import (
    api,
    created,
    make,
    set_source,
    source_record,
    start,
)

from ara.config import DatabaseSettings
from ara.docx_analysis.storage_codec import RetryCheckCommand
from ara.docx_analysis_worker.structured_fixture import fixture_execution
from ara.docx_analysis_worker.wire import StreamDecoder
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine


@pytest.mark.parametrize("host", ["macos", "windows"])
@pytest.mark.parametrize("valid", [True, False])
def test_both_child_bodies_execute_new_fixture_with_the_existing_frame_protocol(
    monkeypatch, host, valid
):
    _, _, request = prepared()
    if not valid:
        request = replace(request, payload=b"PRIVATE")
    child = importlib.import_module("ara.docx_analysis_worker." + host + "._fixture_child")
    frames = []
    if host == "macos":

        def write(fd, raw):
            assert fd == 1
            frames.append(bytes(raw))
            return len(raw)

        monkeypatch.setattr(child.os, "write", write)
        code = child.run_fixture(request.binding, request, "review2")
    else:
        code = child.run_fixture(
            SimpleNamespace(), request.binding, request, "review2", frames.append, 0
        )
    decoder = StreamDecoder(
        request.binding,
        lane="events",
        expected_execution_spec_sha256=request.values["execution_spec_sha256"],
    )
    messages = decoder.feed(b"".join(frames))
    decoder.finish()
    assert [m.kind for m in messages] == ["ready", "stage", "stage", "result" if valid else "error"]
    assert code == (0 if valid else 76)
    if valid:
        assert messages[-1].payload == fixture_api().reply_for(request)
    else:
        assert messages[-1].values["code"] == "adapter_error"
        assert b"PRIVATE" not in b"".join(frames)


def test_both_launch_boundaries_register_fixed_local_model_without_replacing_old_modes():
    from ara.docx_analysis_worker.macos._launch import MODES as mac
    from ara.docx_analysis_worker.windows._adopt import MODES as windows

    for modes in (mac, windows):
        assert "review2" in modes and "review" in modes and "success" in modes
        assert "local_model" in modes and "unknown" not in modes


@pytest.mark.parametrize("value", [None, True, {}, "unknown/v1"])
def test_private_profile_selector_rejects_unknown_values_before_runtime_start(
    world, tmp_path, value
):
    from ara.docx_analysis_worker.supervisor._runtime_models import SupervisorError
    from ara.docx_analysis_worker.supervisor.runtime import _create_supervisor

    w = world["scopes"]["own"]
    with pytest.raises(SupervisorError) as e:
        _create_supervisor(
            settings=DatabaseSettings(world["engine"].url.render_as_string(hide_password=False)),
            user_id=w["runtime"].user_id,
            project_id=w["runtime"].project_id,
            installation_id=uuid4(),
            root=tmp_path,
            execution=fixture_execution(),
            platform=object(),
            source_profile=value,
        )
    assert e.value.code == "validation_error"
    assert counts(world) == (0, 0)


def test_unsupported_host_does_not_fall_back_to_synthetic_platform(world, tmp_path, monkeypatch):
    from ara.docx_analysis_worker.supervisor._runtime_models import SupervisorError

    monkeypatch.setattr(sys, "platform", "unsupported")
    with pytest.raises(SupervisorError) as e:
        make(world, tmp_path, uuid4())
    assert e.value.code == "runtime_unavailable"
    assert counts(world) == (0, 0)


@pytest.mark.parametrize("scope", ["peer", "foreign"])
def test_structured_start_and_retry_recheck_scope_before_accessing_source(world, scope):
    set_source(world, created())
    first = start(world)
    own, other = world["scopes"]["own"], world["scopes"][scope]
    reject(
        "not_found",
        lambda: api().start_saved(
            other["runtime"],
            client_request_id=uuid4(),
            command=own["command"],
            target_provider=None,
            execution=None,
        ),
        404,
    )
    reject(
        "not_found",
        lambda: api().retry_run(
            other["runtime"],
            client_request_id=uuid4(),
            command=RetryCheckCommand(own["doc"], first.summary.run_id),
            execution=fixture_execution(),
        ),
        404,
    )
    assert counts(world) == (1, 1)


def test_corrupt_parent_source_is_not_retried_or_replaced_by_current_document(world):
    w = set_source(world, created())
    first = start(world)
    finish(world, first.summary.run_id)
    with world["engine"].begin() as conn:
        conn.execute(
            text("UPDATE docx_analysis_sources SET source_data=:data"), {"data": b"PRIVATE"}
        )
    reject(
        "storage_error",
        lambda: api().retry_run(
            w["runtime"],
            client_request_id=uuid4(),
            command=RetryCheckCommand(w["doc"], first.summary.run_id),
            execution=fixture_execution(),
        ),
        500,
    )
    assert counts(world) == (1, 1)


def test_unsupported_structured_content_never_creates_a_partial_run(world):
    from test_docx_visible_lists import paragraph
    from test_docx_visible_unlisted import source

    raw, _ = source(paragraph("Unsupported level", level=1))
    set_source(world, raw)
    reject("unsupported_analysis_content", lambda: start(world), 422)
    assert counts(world) == (0, 0)


def test_same_key_changed_command_conflicts_before_calling_provider(world):
    w = set_source(world, created())
    first = start(world)
    key = first.summary.client_request_id
    reject(
        "idempotency_conflict",
        lambda: start(
            world,
            client_request_id=key,
            command=replace(w["command"], command_sequence=3),
            target_provider=None,
        ),
        409,
    )
    assert counts(world) == (1, 1)
    assert source_record(world, first.summary.run_id).source_data == w["target"].data
