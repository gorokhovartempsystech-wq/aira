// Fixed actor protocol and virtual-time acceptance, frozen before implementation.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const [root, name] = process.argv.slice(2);
const { createDocxSession, AUTOSAVE_DELAY_MS } = await import(pathToFileURL(root + "/src/ara/desktop/client/docx-session.mjs"));
assert.equal(AUTOSAVE_DELAY_MS, 120000);
const A = "a".repeat(64), B = "b".repeat(64), C = "c".repeat(64);
const id = n => "00000000-0000-0000-0000-" + String(n).padStart(12, "0");
const clone = x => JSON.parse(JSON.stringify(x));
function initial() {
  const caret = {anchor:{source_sha256:A,part_name:"word/document.xml",path:[0,0]},offset:0,affinity:"right"};
  return {kind:"editor",registry_id:id(1),document_id:id(2),session_id:id(3),command_sequence:"0",base_storage_revision:"7",base_sha256:A,checkpoint_revision:"1",observed_current:{document_id:id(2),title:"Synthetic",storage_revision:"7",current_sha256:A,current_size_bytes:100,created_at:"2026-11-05T00:00:00+00:00",updated_at:"2026-11-05T00:00:00+00:00"},observed_checkpoint_revision:"1",observed_checkpoint_phase:"empty",state:"editable",recovery_operation_id:null,last_command:null,active_command:null,position_id:"0",selection:{anchor:clone(caret),focus:clone(caret)},document:{session_revision:"0",source_sha256:A,main_part:"word/document.xml",size_bytes:100,is_dirty:false,undo_depth:0,redo_depth:0}};
}
const flush = async () => { for(let i=0;i<20;i++) await Promise.resolve(); };
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
function rig(options={}) {
 let view=clone(options.view??initial()), now=0, timerId=0, uuid=100;
 const timers=new Map(), calls=[], states=[];
 let behavior=null;
 function ack(request) {
  const body=JSON.parse(request.body), op=request.path.split("/").at(-1);
  assert.equal(body.expected_command_sequence,view.command_sequence);
  assert.equal(body.expected_session_revision,view.document.session_revision);
  const out=clone(view), action=op==="commands"?body.command.action:op;
  out.command_sequence=(BigInt(view.command_sequence)+1n).toString();
  if(op==="commands" && action!=="capture" && !(action==="insert_text" && body.command.value==="")) {
   out.document.session_revision=(BigInt(view.document.session_revision)+1n).toString();
   out.position_id=out.document.session_revision;
   out.document.source_sha256=action==="undo"?A:(view.document.source_sha256===B?C:B);
   out.document.is_dirty=out.document.source_sha256!==out.base_sha256;
   out.document.undo_depth=1;
   for(const p of [out.selection.anchor,out.selection.focus])p.anchor.source_sha256=out.document.source_sha256;
  }
  if(op==="checkpoint"||op==="save") {
   out.checkpoint_revision=(BigInt(view.checkpoint_revision)+1n).toString();
   out.observed_checkpoint_revision=out.checkpoint_revision;out.observed_checkpoint_phase="working";
   if(op==="save") {
    out.base_sha256=out.document.source_sha256;out.document.is_dirty=false;
    out.base_storage_revision=(BigInt(view.base_storage_revision)+1n).toString();
    out.observed_current.storage_revision=out.base_storage_revision;
    out.observed_current.current_sha256=out.base_sha256;
   }
  }
  out.last_command={command_id:body.command_id,request_sha256:"d".repeat(64),action,expected_command_sequence:body.expected_command_sequence,expected_session_revision:body.expected_session_revision,result_command_sequence:out.command_sequence,result_session_revision:out.document.session_revision,result_position_id:out.position_id};
  view=out;return {status:200,body:clone(out)};
 }
 const r={calls,states,timers,ack,setBehavior(fn){behavior=fn},server(){return clone(view)}};
 r.client=createDocxSession({view:clone(view),send:async request=>{calls.push(clone(request));return behavior?behavior(request):ack(request)},makeId:()=>id(uuid++),schedule:(fn,delay)=>{const n=++timerId;timers.set(n,{fn,at:now+delay});return n},cancel:n=>timers.delete(n),onState:state=>{states.push(clone(state));options.onState?.(state)}});
 r.tick=async ms=>{const end=now+ms;for(;;){const next=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;const[n,t]=next;timers.delete(n);now=t.at;t.fn();await flush()}now=end;await flush()};
 r.edit=text=>r.client.edit({action:"insert_text",value:text});
 return r;
}
const cases={
 async inert(){const r=rig();assert.equal(r.calls.length,0);assert.equal(r.timers.size,0);r.client.start();assert.equal(r.calls.length,0);assert.equal(r.timers.size,0)},
 async deadline(){const r=rig();r.client.start();await r.edit("First");await r.tick(119999);assert.equal(r.calls.length,1);await r.tick(1);assert.equal(r.calls.length,2);assert.ok(r.calls[1].path.endsWith("/checkpoint"));assert.equal(r.client.status().uncheckpointed,false);assert.equal(r.client.snapshot().document.is_dirty,true)},
 async continuous(){const r=rig();r.client.start();await r.edit("First");for(let i=0;i<5;i++){await r.tick(20000);await r.edit("More")}await r.tick(20000);assert.equal(r.calls.filter(x=>x.path.endsWith("/checkpoint")).length,1)},
 async unchanged(){const r=rig();r.client.start();await r.edit("");await r.tick(240000);assert.equal(r.calls.length,1);assert.equal(r.timers.size,0)},
 async capture(){const r=rig();r.client.start();await r.edit("First");await r.tick(60000);await r.client.edit({action:"capture",value:r.client.snapshot().selection});await r.tick(60000);assert.ok(r.calls.at(-1).path.endsWith("/checkpoint"))},
 async initial_dirty(){const view=initial();view.checkpoint_revision="2";view.observed_checkpoint_revision="2";view.observed_checkpoint_phase="working";view.document.source_sha256=B;view.document.is_dirty=true;for(const p of [view.selection.anchor,view.selection.focus])p.anchor.source_sha256=B;const r=rig({view});assert.equal(r.timers.size,0);r.client.start();await r.tick(120000);assert.equal(r.calls.length,1);assert.ok(r.calls[0].path.endsWith("/checkpoint"))},
 async persisted_dirty(){const r=rig();r.client.start();await r.edit("First");await r.tick(120000);await r.tick(600000);assert.equal(r.calls.length,2);assert.equal(r.client.snapshot().document.is_dirty,true)},
 async undo_before(){const r=rig();r.client.start();await r.edit("First");await r.client.edit({action:"undo",value:null});await r.tick(120000);assert.equal(r.calls.length,2);assert.equal(r.client.snapshot().document.is_dirty,false)},
 async undo_after(){const r=rig();r.client.start();await r.edit("First");await r.tick(120000);await r.client.edit({action:"undo",value:null});assert.equal(r.client.snapshot().document.is_dirty,false);await r.tick(120000);assert.equal(r.calls.filter(x=>x.path.endsWith("/checkpoint")).length,2)},
 async due_while_busy(){const r=rig();r.client.start();await r.edit("First");await r.tick(119000);const gate=deferred();r.setBehavior(req=>gate.promise.then(()=>r.ack(req)));const write=r.edit("Second");await flush();await r.tick(1000);assert.equal(r.calls.length,2);gate.resolve();await write;await flush();assert.equal(r.calls.length,3);assert.ok(r.calls[2].path.endsWith("/checkpoint"))},
 async busy(){const r=rig();r.client.start();const gate=deferred();r.setBehavior(req=>gate.promise.then(()=>r.ack(req)));const first=r.edit("First");await flush();await assert.rejects(r.edit("Second"),e=>e.code==="busy");assert.equal(r.calls.length,1);gate.resolve();await first},
 async lost_ack(){const r=rig();r.client.start();let receipt;r.setBehavior(req=>{receipt=r.ack(req);throw Error("private synthetic failure")});await assert.rejects(r.edit("First"));const before=r.client.snapshot();assert.equal(before.command_sequence,"0");await assert.rejects(r.edit("Second"));r.setBehavior(()=>receipt);await r.client.retry();assert.deepEqual(r.calls[0],r.calls[1]);assert.equal(r.client.snapshot().command_sequence,"1");assert.equal(r.server().command_sequence,"1")},
 async immutable(){const r=rig();r.client.start();const command={action:"insert_text",value:"Original"};r.setBehavior(()=>{throw Error("lost")});await assert.rejects(r.client.edit(command));command.value="Changed";r.setBehavior(req=>r.ack(req));await r.client.retry();assert.deepEqual(r.calls[0],r.calls[1]);assert.equal(JSON.parse(r.calls[1].body).command.value,"Original")},
 async wrong_identity(){const r=rig();r.client.start();r.setBehavior(req=>{const out=r.ack(req);out.body.session_id=id(99);return out});await assert.rejects(r.edit("First"));assert.equal(r.client.snapshot().command_sequence,"0");assert.equal(r.client.status().canRetry,true)},
 async wrong_counter(){const r=rig();r.client.start();r.setBehavior(req=>{const out=r.ack(req);out.body.command_sequence="3";return out});await assert.rejects(r.edit("First"));assert.equal(r.client.snapshot().command_sequence,"0")},
 async wrong_receipt(){const r=rig();r.client.start();r.setBehavior(req=>{const out=r.ack(req);out.body.last_command.command_id=id(99);return out});await assert.rejects(r.edit("First"));assert.equal(r.client.snapshot().command_sequence,"0")},
 async bigint(){const view=initial();view.command_sequence="9007199254740993";const r=rig({view});r.client.start();await r.edit("First");assert.equal(JSON.parse(r.calls[0].body).expected_command_sequence,"9007199254740993");assert.equal(r.client.snapshot().command_sequence,"9007199254740994")},
 async exhausted(){const view=initial();view.command_sequence="9223372036854775807";const r=rig({view});r.client.start();await assert.rejects(r.edit("First"));assert.equal(r.calls.length,0)},
 async refusal(){const r=rig();r.client.start();r.setBehavior(()=>({status:422,body:{code:"unsupported_intent"}}));await assert.rejects(r.edit("First"));assert.equal(r.client.status().canEdit,true);r.setBehavior(req=>r.ack(req));await r.edit("Second");assert.notEqual(JSON.parse(r.calls[0].body).command_id,JSON.parse(r.calls[1].body).command_id);assert.equal(JSON.parse(r.calls[1].body).expected_command_sequence,"0")},
 async conflict(){const r=rig();r.client.start();r.setBehavior(()=>({status:409,body:{code:"checkpoint_conflict"}}));await assert.rejects(r.edit("First"));assert.equal(r.client.status().canEdit,false);await r.tick(600000);assert.equal(r.calls.length,1)},
 async expired(){const r=rig();r.client.start();r.setBehavior(()=>({status:410,body:{code:"editor_session_expired"}}));await assert.rejects(r.edit("First"));assert.equal(r.client.status().canEdit,false);assert.equal(r.client.snapshot().session_id,id(3))},
 async control_error(){const r=rig();r.client.start();await r.edit("First");r.setBehavior(()=>({status:500,body:{code:"editor_error"}}));await assert.rejects(r.client.checkpoint());assert.equal(r.client.status().canEdit,false);r.setBehavior(req=>r.ack(req));await r.client.retry();assert.deepEqual(r.calls[1],r.calls[2]);assert.equal(r.client.status().uncheckpointed,false)},
 async callback(){const r=rig({onState:()=>{throw Error("UI failed")}});r.client.start();await r.edit("First");await r.tick(120000);assert.equal(r.client.snapshot().command_sequence,"2")},
 async stop_pending(){const r=rig();r.client.start();const gate=deferred();r.setBehavior(req=>gate.promise.then(()=>r.ack(req)));const first=r.edit("First");await flush();r.client.stop();gate.resolve();await first;await r.tick(600000);assert.equal(r.calls.length,1);assert.equal(r.timers.size,0);assert.equal(r.client.snapshot().command_sequence,"1")},
 async independent(){const view=initial();view.document_id=id(20);view.observed_current.document_id=id(20);view.session_id=id(30);const a=rig(),b=rig({view});a.client.start();b.client.start();await a.edit("A");await b.edit("B");a.client.stop();await a.tick(120000);await b.tick(120000);assert.equal(a.calls.length,1);assert.equal(b.calls.length,2)},
 async save(){const r=rig();r.client.start();await r.edit("First");await r.client.save();assert.equal(r.client.snapshot().document.is_dirty,false);await r.tick(120000);assert.equal(r.calls.length,2);assert.ok(r.calls[1].path.endsWith("/save"))},
 async detached(){const r=rig();r.client.start();const before=r.client.snapshot();before.command_sequence="999";before.selection.anchor.offset=999;await r.edit("First");assert.equal(JSON.parse(r.calls[0].body).expected_command_sequence,"0");assert.notEqual(r.client.snapshot().selection.anchor.offset,999)}
};

cases.control_source = async () => {
 const r=rig();r.client.start();await r.edit("First");const before=r.client.snapshot();
 r.setBehavior(req=>{const out=r.ack(req);out.body.document.source_sha256=C;return out});
 await assert.rejects(r.client.checkpoint());assert.deepEqual(r.client.snapshot(),before);
};
cases.busy_response = async () => {
 const r=rig();r.client.start();r.setBehavior(()=>({status:503,body:{code:"editor_busy"}}));
 await assert.rejects(r.edit("First"));await r.tick(600000);assert.equal(r.calls.length,1);
 r.setBehavior(req=>r.ack(req));await r.client.retry();assert.deepEqual(r.calls[0],r.calls[1]);
};
cases.refused_retry = async () => {
 const r=rig();r.client.start();r.setBehavior(()=>{throw Error("lost")});
 await assert.rejects(r.edit("First"));r.setBehavior(()=>({status:422,body:{code:"validation_error"}}));
 await assert.rejects(r.client.retry());assert.equal(r.client.status().canEdit,false);
 assert.deepEqual(r.calls[0],r.calls[1]);
};
cases.request_too_large = async () => {
 const r=rig();r.client.start();r.setBehavior(()=>({status:413,body:{code:"editor_request_too_large"}}));
 await assert.rejects(r.edit("First"));assert.equal(r.client.status().canEdit,true);
 assert.equal(r.client.snapshot().command_sequence,"0");
};
cases.unauthorized = async () => {
 const r=rig();r.client.start();r.setBehavior(()=>({status:403,body:{code:"license_required"}}));
 await assert.rejects(r.edit("First"));assert.equal(r.client.status().canEdit,false);
 await r.tick(600000);assert.equal(r.calls.length,1);
};
cases.safe_error = async () => {
 const r=rig();r.client.start();r.setBehavior(()=>{throw Error("PRIVATE_SYNTHETIC_PAYLOAD")});
 await assert.rejects(r.edit("PRIVATE_SYNTHETIC_PAYLOAD"),e=>!String(e).includes("PRIVATE_SYNTHETIC_PAYLOAD"));
 assert.ok(!JSON.stringify(r.states).includes("PRIVATE_SYNTHETIC_PAYLOAD"));
};
cases.noncanonical = async () => {
 for(const value of [1,"01","-1","9223372036854775808"]){const view=initial();view.command_sequence=value;assert.throws(()=>rig({view}))}
};
cases.stop_timer = async () => {
 const r=rig();r.client.start();await r.edit("First");r.client.stop();await r.tick(600000);
 assert.equal(r.calls.length,1);assert.equal(r.timers.size,0);assert.equal(r.client.snapshot().document.is_dirty,true);
};
cases.invalid_json = async () => {
 const r=rig();r.client.start();await assert.rejects(r.client.edit({action:"insert_text",value:Infinity}));
 assert.equal(r.calls.length,0);
};

assert.ok(Object.hasOwn(cases,name),"Unknown case");await cases[name]();process.stdout.write("ok "+name+"\n");
