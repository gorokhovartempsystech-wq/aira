"""Bounded pinned Fetch transport and actual owned licensed DOCX autosave/recovery."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[2]
CASES = (
    "inert",
    "exact",
    "origin",
    "token",
    "identity",
    "paths",
    "input_bounds",
    "status",
    "redirects",
    "response_url",
    "media",
    "malformed",
    "declared_length",
    "streamed_limit",
    "exact_limit",
    "header_deadline",
    "body_deadline",
    "busy",
    "safe_error",
    "cancel_error",
    "late_deadline",
    "chunks",
    "late_fetch",
    "timer_failure",
    "hanging_cancel",
)


def node():
    bundled = Path(sys.base_prefix).parent / "node/bin/node"
    result = shutil.which("node") or (str(bundled) if bundled.is_file() else None)
    assert result is not None, "Node.js required for Fetch acceptance"
    return result


@pytest.mark.parametrize("case", CASES)
def test_pinned_editor_http_transport(case):
    run = subprocess.run(
        [node(), str(ROOT / "tests/acceptance/docx_client_transport_cases.mjs"), str(ROOT), case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == "ok " + case + "\n"


def invoke_owned(connection, view, mode):
    job = dict(
        root=str(ROOT),
        origin=connection.origin,
        token=connection.session_token.hex(),
        view=view,
        mode=mode,
    )
    run = subprocess.run(
        [node(), str(ROOT / "tests/acceptance/docx_client_transport_owned.mjs")],
        cwd=ROOT,
        input=json.dumps(job),
        capture_output=True,
        text=True,
        timeout=75,
    )
    # The capability is never an argument, fixture file, assertion rendering or diagnostic.
    token = job.pop("token")
    assert token not in run.stdout + run.stderr, "child emitted a capability"
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(sys.platform != "darwin", reason="owned macOS licensed desktop")
def test_real_fetch_lost_ack_autosave_restart_recover_and_exact_auxiliary_parts(tmp_path):
    from test_desktop_composition import activate, license_phase, running
    from test_desktop_server import http_for
    from test_desktop_structured_review import imported
    from test_desktop_word_review import word_config
    from test_docx_editor_http import opened, path, root
    from test_docx_visible_word import parts, source

    cfg = word_config(tmp_path)
    records = []
    prefix = "Автосохранение 🧪 "
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        for name in ("plain", "merged_table"):
            raw = source(name)
            item = imported(http, raw)
            view, _ = opened(http, item)
            checkpointed = invoke_owned(desktop.connection(), view, "checkpoint")
            assert http.get(path(item, view)).json() == checkpointed
            assert checkpointed["document"]["is_dirty"]
            assert checkpointed["command_sequence"] == "2"
            assert checkpointed["checkpoint_revision"] == "2"
            assert http.get(root(item) + "/content").content == raw
            records.append((item, raw, checkpointed))
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        license_phase(http, "active")
        for item, raw, checkpointed in records:
            restored, _ = opened(http, item, "recover")
            assert restored["registry_id"] != checkpointed["registry_id"]
            assert (
                restored["document"]["source_sha256"] == checkpointed["document"]["source_sha256"]
            )
            assert restored["document"]["session_revision"] == "0"
            assert restored["document"]["is_dirty"]
            assert http.get(root(item) + "/content").content == raw
            saved = invoke_owned(desktop.connection(), restored, "save")
            assert http.get(path(item, restored)).json() == saved
            before, after = parts(raw), parts(http.get(root(item) + "/content").content)
            assert before.keys() == after.keys()
            assert all(before[k] == after[k] for k in before if k != "word/document.xml")
            assert before["word/document.xml"] != after["word/document.xml"]
            xml = ElementTree.fromstring(after["word/document.xml"])
            texts = "".join(
                x.text or ""
                for x in xml.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
            )
            assert texts.count(prefix) == 1
            assert "MUST_NOT_APPEAR" not in texts
    assert [r.operation for r in cfg.transport.requests] == ["activate", "check"]


REVIEW_CASES = {
    "null_dependencies": """
for(const field of ['fetchImpl','schedule','cancel'])assert.throws(()=>rig({[field]:null}));
""",
    "configuration_getter": """
let touched=false;
const options={origin,sessionToken:token,documentId,sessionId,
 get fetchImpl(){touched=true;throw Error('PRIVATE_GETTER')}};
assert.throws(()=>createEditorTransport(options),e=>e.code==='invalid_input');
assert.equal(touched,false);
""",
    "request_getter": """
let touched=false;const r=rig();
await assert.rejects(r.send({path,get body(){touched=true;throw Error('PRIVATE_GETTER')}}),
 e=>e.code==='invalid_input');
assert.equal(touched,false);
assert.equal(r.calls.length,0);
""",
    "utf8_request_budget": """
const r=rig();await assert.rejects(r.send({path:path.replace('/commands','/save'),
 body:'я'.repeat(65536)}));
assert.equal(r.calls.length,0);
""",
    "split_utf8_reply": """
const text=JSON.stringify({value:'Ёж 🧪'}),bytes=new TextEncoder().encode(text);const r=rig();
r.set(()=>response({stream:new ReadableStream({start(c){
 for(const b of bytes)c.enqueue(new Uint8Array([b]));c.close()}}),
 headers:{'Content-Type':'Application/JSON; charset=UTF-8',
 'Content-Length':String(bytes.length)}}));
assert.deepEqual((await r.send(request)).body,{value:'Ёж 🧪'});
""",
    "body_read_failure": """
const r=rig();
r.set(()=>response({stream:new ReadableStream({pull(c){c.error(Error(token+' PRIVATE_BODY'))}})}));
await assert.rejects(r.send(request),
 e=>e.code==='invalid_response'&&!String(e).includes('PRIVATE_BODY'));
assert.equal(r.timers.size,0);r.set(()=>response());
assert.equal((await r.send(request)).status,200);
""",
    "late_old_fetch_new_request": """
const r=rig();let release;r.set(()=>new Promise(resolve=>release=resolve));
const expired=assert.rejects(r.send(request));await flush();r.fire();await expired;
r.set(()=>response());
assert.equal((await r.send(request)).status,200);
let cancelled=false;release(response({stream:new ReadableStream({cancel(){cancelled=true}})}));
await flush();
assert.equal(cancelled,true);
assert.equal(r.calls.length,2);
assert.equal(r.timers.size,0);
""",
    "old_timer_new_request": """
const callbacks=[],signals=[];let release,first=true;
const send=createEditorTransport({origin,sessionToken:token,documentId,sessionId,
 schedule:fn=>{callbacks.push(fn);return callbacks.length},cancel:()=>{},
 fetchImpl:async(url,init)=>{signals.push(init.signal);if(first){first=false;return response()}
 return new Promise(resolve=>release=resolve)}});
assert.equal((await send(request)).status,200);const second=send(request);await flush();
callbacks[0]();await flush();
assert.equal(signals[1].aborted,false);
release(response());
assert.equal((await second).status,200);
""",
    "independent_actors": """
let release;const a=rig(),b=rig({sessionId:documentId});
a.set(()=>new Promise(resolve=>release=resolve));const first=a.send(request);await flush();
const otherPath=path.replace('/'+sessionId+'/', '/'+documentId+'/');
b.set(()=>response({url:origin+otherPath}));
assert.equal((await b.send({path:otherPath,body})).status,200);
release(response());await first;
""",
    "private_status": """
const r=rig();
r.set(()=>({status:200,url:origin+path,redirected:false,type:'basic',
 headers:{get(){throw Error(token+' PRIVATE_HEADERS')}},body:null}));
await assert.rejects(r.send(request),
 e=>!JSON.stringify(e).includes(token)&&!String(e).includes('PRIVATE_HEADERS'));
assert.equal(r.timers.size,0);
""",
    "real_redirect": """
const {createServer}=await import('node:http');let foreignHits=0;
const target=createServer((req,res)=>{foreignHits++;res.end('{}')});
await new Promise(resolve=>target.listen(0,'127.0.0.1',resolve));
const server=createServer((req,res)=>{res.writeHead(307,{Location:`http://127.0.0.1:${target.address().port}/catch`});res.end()});
try{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const send=createEditorTransport({origin:`http://127.0.0.1:${server.address().port}`,sessionToken:token,documentId,sessionId});
 await assert.rejects(send(request));await new Promise(resolve=>setTimeout(resolve,25));
 assert.equal(foreignHits,0);
}finally{
 for(const s of [server,target]){s.closeAllConnections();
 await new Promise(resolve=>s.close(resolve))}
}
""",
}


@pytest.mark.parametrize("case", REVIEW_CASES)
def test_editor_transport_independent_review(case):
    frozen = (ROOT / "tests/acceptance/docx_client_transport_cases.mjs").read_text()
    prelude = frozen[: frozen.rindex("\nassert.ok(Object.hasOwn(cases,name));")]
    run = subprocess.run(
        [node(), "--input-type=module", "-", str(ROOT), case],
        input=prelude + "\n" + REVIEW_CASES[case],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == ""
