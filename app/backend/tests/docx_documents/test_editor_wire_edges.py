"""Pure wire input/output boundaries without registry or database access."""

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from ara.docx_documents._dto import MAX_REVISION
from ara.docx_editor._models import ActiveCommand, CommandReceipt
from ara.docx_package.projection._models import Cell, Row, Table
from tests.acceptance.test_docx_checkpoints import reject
from tests.acceptance.test_docx_editor_wire import anchor, api, identity, view


@pytest.mark.parametrize(
    "action", ["enter", "join_previous", "join_next", "insert_soft_break", "undo", "redo"]
)
def test_all_no_value_intents_and_unknown_payload(action):
    request = {**identity(), "command": dict(action=action)}
    decoded = api().decode_command(request)
    assert decoded["command"].action == action and decoded["command"].after is None
    request["command"]["value"] = "SYNTHETIC_PRIVATE"
    reject(lambda: api().decode_command(request), "validation_error", 422)


def test_input_is_detached_and_bool_offset_is_rejected():
    source = view()
    a = anchor(source)
    selection = dict(
        anchor=dict(anchor=a, offset=1, affinity="left"), focus=dict(anchor=a, offset=0)
    )
    request = {**identity(), "command": dict(action="capture", value=selection)}
    result = api().decode_command(request)
    a["path"][0] = 999
    assert result["command"].value.anchor.anchor.path[0] != 999
    selection["anchor"]["offset"] = True
    reject(lambda: api().decode_command(request), "validation_error", 422)


def test_batches_bound_lengths_and_types_before_constructing_native_records():
    source = view()
    a = anchor(source)
    format_request = {
        **identity(),
        "command": dict(
            action="format", value=[dict(anchor=a, expected_text="x", style_id="x" * 256)]
        ),
    }
    reject(lambda: api().decode_command(format_request), "validation_error", 422)
    insert = {
        **identity(),
        "command": dict(
            action="structure",
            value=[dict(kind="insert", anchor=a, expected_text="x", texts=["x"] * 1001)],
        ),
    }
    reject(lambda: api().decode_command(insert), "validation_error", 422)
    giant = {**identity(), "command": dict(action="paste_text", value="x" * 1000001)}
    reject(lambda: api().decode_command(giant), "validation_error", 422)
    bad = {**identity(), "command": dict(action="range_edit", value=[{}])}
    reject(lambda: api().decode_command(bad), "validation_error", 422)


def test_active_and_latest_metadata_preserve_big_counters_without_text():
    source = view()
    receipt = CommandReceipt(uuid4(), "a" * 64, "capture", MAX_REVISION - 1, 0, MAX_REVISION, 0, 0)
    active = ActiveCommand(
        uuid4(), "save", "b" * 64, MAX_REVISION, 0, "save_pending", uuid4(), "committed"
    )
    source = replace(
        source,
        command_sequence=MAX_REVISION,
        last_command=receipt,
        active_command=active,
        state="operation_pending",
    )
    encoded = json.loads(api().encode_reply(source))
    assert encoded["active_command"]["expected_command_sequence"] == str(MAX_REVISION)
    assert encoded["last_command"]["result_command_sequence"] == str(MAX_REVISION)
    assert encoded["active_command"]["save_state"] == "committed"
    assert encoded["active_command"]["operation_id"] == str(active.operation_id)


def test_metadata_size_and_projection_cycles_are_bounded():
    source = deepcopy(view())
    for caret in (source.editor.selection.anchor, source.editor.selection.focus):
        object.__setattr__(caret.anchor, "part_name", "x" * 65536)
    reject(lambda: api().encode_reply(source), "editor_reply_limit_exceeded", 413)
    source = deepcopy(view())
    a = source.editor.selection.anchor.anchor
    table = Table(a, (), None)
    cell = Cell(a, (table,), None, None, None)
    row = Row(a, (cell,), None)
    object.__setattr__(table, "rows", (row,))
    object.__setattr__(source.editor.document.projection, "blocks", (table,))
    reject(lambda: api().encode_projection(source), "editor_reply_limit_exceeded", 413)


def test_unknown_nested_projection_type_cannot_leak_attributes():
    source = deepcopy(view())
    object.__setattr__(
        source.editor.document.projection, "blocks", (source.editor.document.projection.source,)
    )
    reject(lambda: api().encode_projection(source), "editor_error", 500)


def test_first_import_valid_decode_and_encode_have_no_external_io():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid,sys,copy,contextlib,functools
import hashlib,re,zipfile,xml.etree.ElementTree,typing,datetime,threading,inspect
from pathlib import Path
import sqlalchemy,psycopg
from ara.documents.storage import DocumentError
from ara.docx_editor._models import ClosedEditor
from uuid import uuid4
record=ClosedEditor(uuid4(),uuid4(),uuid4(),'release_local',None)
assert 'ara.docx_editor.wire' not in sys.modules
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes'),
                 (sqlalchemy,'create_engine'),(psycopg,'connect')):
 setattr(obj,name,forbidden)
from ara.docx_editor.wire import decode_control,encode_reply
p=decode_control(dict(command_id=str(uuid4()),expected_command_sequence='0',expected_session_revision='0'))
assert p['expected_command_sequence']==0
assert encode_reply(record)
try:decode_control({'bad':'SYNTHETIC_PRIVATE'})
except DocumentError as exc:assert exc.code=='validation_error'
else:raise AssertionError('Expected refusal')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={"PYTHONPATH": str(Path.cwd() / "src")},
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout
