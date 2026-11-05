"""Deterministic real ESM coordinator behavior, no DOM, timer sleeps or network."""

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CASES = (
    "inert",
    "deadline",
    "continuous",
    "unchanged",
    "capture",
    "initial_dirty",
    "persisted_dirty",
    "undo_before",
    "undo_after",
    "due_while_busy",
    "busy",
    "lost_ack",
    "immutable",
    "wrong_identity",
    "wrong_counter",
    "wrong_receipt",
    "bigint",
    "exhausted",
    "refusal",
    "conflict",
    "expired",
    "control_error",
    "callback",
    "stop_pending",
    "independent",
    "save",
    "detached",
    "control_source",
    "busy_response",
    "refused_retry",
    "request_too_large",
    "unauthorized",
    "safe_error",
    "noncanonical",
    "stop_timer",
    "invalid_json",
)


@pytest.mark.parametrize("case", CASES)
def test_docx_client_protocol_and_fixed_autosave(case):
    bundled = Path(sys.base_prefix).parent / "node/bin/node"
    node = shutil.which("node") or (str(bundled) if bundled.is_file() else None)
    assert node is not None, "Node.js required for deterministic client acceptance"
    run = subprocess.run(
        [node, str(ROOT / "tests/acceptance/docx_client_session_cases.mjs"), str(ROOT), case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == "ok " + case + "\n"


def test_client_modules_are_explicit_package_assets():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "*.mjs" in config["tool"]["setuptools"]["package-data"]["ara.desktop.client"]
    assert (ROOT / "src/ara/desktop/client/__init__.py").is_file()


REVIEW_CASES = {
    "schedule_failure": """
const r=rig();let current=initial();let nextId=700;
const client=createDocxSession({view:current,send:r.ack,makeId:()=>id(nextId++),
 schedule:()=>{throw Error('PRIVATE_TIMER')},cancel:()=>{}});
client.start();const result=await client.edit({action:'insert_text',value:'A'});
assert.equal(result.command_sequence,'1');assert.equal(client.status().canEdit,true);
assert.equal(client.status().phase,'scheduler_error');
assert.ok(!JSON.stringify(client.status()).includes('PRIVATE_TIMER'));
await client.checkpoint();assert.equal(client.status().uncheckpointed,false);
""",
    "cancel_failure": """
const r=rig();let fire;let nextId=700;
const client=createDocxSession({view:initial(),send:r.ack,makeId:()=>id(nextId++),
 schedule:fn=>{fire=fn;return 1},cancel:()=>{throw Error('PRIVATE_TIMER')}});
client.start();await client.edit({action:'insert_text',value:'A'});
const saved=await client.save();assert.equal(saved.document.is_dirty,false);
assert.equal(client.status().uncheckpointed,false);fire();await flush();
assert.equal(client.snapshot().command_sequence,'2');
client.stop();assert.equal(client.status().phase,'stopped');
""",
    "late_cancelled_timer": """
const r=rig();const callbacks=[];let nextId=700;
const client=createDocxSession({view:initial(),send:r.ack,makeId:()=>id(nextId++),
 schedule:fn=>{callbacks.push(fn);return callbacks.length},cancel:()=>{}});
client.start();await client.edit({action:'insert_text',value:'A'});await client.save();
await client.edit({action:'insert_text',value:'B'});callbacks[0]();await flush();
assert.equal(client.snapshot().command_sequence,'3');
callbacks[1]();await flush();assert.equal(client.snapshot().command_sequence,'4');
""",
    "getter_rejected_without_execution": """
const r=rig();let invoked=false;r.client.start();
const command={get action(){invoked=true;throw Error('PRIVATE_GETTER')},value:'A'};
await assert.rejects(r.client.edit(command),e=>e.code==='invalid_input');
assert.equal(invoked,false);assert.equal(r.calls.length,0);
""",
    "aggregate_limit": """
const r=rig();r.client.start();
const command={action:'format',value:Array(20).fill('x'.repeat(1024*1024))};
await assert.rejects(r.client.edit(command),e=>e.code==='invalid_input');
assert.equal(r.calls.length,0);assert.equal(r.client.status().canEdit,true);
""",
    "missing_main_part": """
const view=initial();delete view.document.main_part;
for(const p of [view.selection.anchor,view.selection.focus])delete p.anchor.part_name;
assert.throws(()=>rig({view}));
""",
    "control_checkpoint_exhausted": """
const view=initial();view.checkpoint_revision='9223372036854775807';
view.observed_checkpoint_revision=view.checkpoint_revision;const r=rig({view});r.client.start();
await assert.rejects(r.client.checkpoint(),e=>e.code==='counter_exhausted');
assert.equal(r.calls.length,0);
""",
    "blocked_identity_at_deadline": """
const r=rig();let fire;let nextId=700;
const client=createDocxSession({view:initial(),send:r.ack,makeId:()=>{
 if(nextId===701)throw Error('PRIVATE_UUID');return id(nextId++);
},schedule:fn=>{fire=fn;return 1},cancel:()=>{}});
client.start();await client.edit({action:'insert_text',value:'A'});fire();await flush();
assert.equal(client.snapshot().command_sequence,'1');assert.equal(client.status().phase,'error');
assert.equal(client.status().uncheckpointed,true);
""",
    "reentrant_callback": """
const r=rig();let client;let nextId=700;let nested;
client=createDocxSession({view:initial(),send:r.ack,makeId:()=>id(nextId++),
 schedule:()=>1,cancel:()=>{},onState:s=>{
 if(s.busy&&!nested)nested=client.edit({action:'insert_text',value:'Second'}).catch(e=>e.code);
}});client.start();await client.edit({action:'insert_text',value:'First'});
assert.equal(await nested,'busy');assert.equal(client.snapshot().command_sequence,'1');
""",
    "unhandled_rejection_isolated": """
const unhandled=[];process.on('unhandledRejection',e=>unhandled.push(e));
const r=rig();let nextId=700;
const client=createDocxSession({view:initial(),send:r.ack,makeId:()=>id(nextId++),
 schedule:()=>1,cancel:()=>{},onState:()=>Promise.reject(Error('PRIVATE_ASYNC_UI'))});
client.start();await client.edit({action:'insert_text',value:'First'});await client.checkpoint();
await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(unhandled,[]);
""",
}


REVIEW_CASES["canonical_wire_strings"] = r"""
for(const suffix of ['\n','\r','\r\n','\u2028','\u2029']){
 const sequence=initial();sequence.command_sequence='1'+suffix;
 assert.throws(()=>rig({view:sequence}));
 const identity=initial();identity.session_id+=suffix;assert.throws(()=>rig({view:identity}));
 const digest=initial();digest.base_sha256+=suffix;digest.document.source_sha256+=suffix;
 digest.observed_current.current_sha256+=suffix;
 for(const p of [digest.selection.anchor,digest.selection.focus])p.anchor.source_sha256+=suffix;
 assert.throws(()=>rig({view:digest}));
}
"""


@pytest.mark.parametrize("case", REVIEW_CASES)
def test_docx_client_independent_review(case):
    bundled = Path(sys.base_prefix).parent / "node/bin/node"
    node = shutil.which("node") or str(bundled)
    frozen = (ROOT / "tests/acceptance/docx_client_session_cases.mjs").read_text()
    prelude = frozen[: frozen.rindex("\nassert.ok(Object.hasOwn(cases,name)")]
    run = subprocess.run(
        [node, "--input-type=module", "-", str(ROOT), case],
        input=prelude + "\n" + REVIEW_CASES[case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == ""
