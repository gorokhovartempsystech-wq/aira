import assert from 'node:assert/strict';import {pathToFileURL} from 'node:url';
const root=process.argv[2],name=process.argv[3];
const {createDocumentWorkspace}=await import(pathToFileURL(root+'/src/ara/desktop/client/document-workspace.mjs'));
const id=n=>'00000000-0000-0000-0000-'+String(n).padStart(12,'0'),hash='a'.repeat(64),doc=id(2);
function view(){const caret={anchor:{source_sha256:hash,part_name:'word/document.xml',path:[0,0]},offset:0,affinity:'right'};return {kind:'editor',registry_id:id(1),document_id:doc,session_id:id(3),command_sequence:'0',base_storage_revision:'1',base_sha256:hash,checkpoint_revision:'1',observed_current:{document_id:doc,storage_revision:'1',current_sha256:hash},observed_checkpoint_revision:'1',observed_checkpoint_phase:'empty',state:'editable',recovery_operation_id:null,last_command:null,active_command:null,position_id:'0',selection:{anchor:caret,focus:caret},document:{session_revision:'0',source_sha256:hash,main_part:'word/document.xml',is_dirty:false,undo_depth:0,redo_depth:0}}}
let recoveryPhase='empty',loseOpen=false,loseClose=false,expired=false,prove=true,checkpointFail=false,editorBusy=false,serial=100,checkpointCalls=0,opened=0;
const calls=[];let local=view();
function recovery(){return {kind:'recovery',registry_id:id(1),open_sequence:'0',document:{document_id:doc,current_sha256:prove?hash:'b'.repeat(64)},checkpoint_revision:'2',phase:recoveryPhase,working_sha256:prove?hash:'b'.repeat(64)}}
const send=async req=>{calls.push({...req});if(req.method==='GET')return {status:200,body:recovery()};
 if(req.path.endsWith('/editor-sessions')){opened++;if(loseOpen){loseOpen=false;throw Error('lost')};let v=view();if(recoveryPhase==='pending'){v.state='recovery_pending';v.recovery_operation_id=id(8)}if(name==='foreign')v.document_id=id(99);return {status:200,body:{kind:'opened',view:v,accepted_open_sequence:'0',next_open_sequence:'1'}}}
 if(req.path.endsWith('/reconcile')){const b=JSON.parse(req.body);let v=view();v.command_sequence='1';v.checkpoint_revision='3';v.observed_checkpoint_revision='3';v.last_command={command_id:b.command_id,request_sha256:hash,action:'save',expected_command_sequence:'0',expected_session_revision:'0',result_command_sequence:'1',result_session_revision:'0',result_position_id:'0'};return {status:200,body:v}}
 if(expired)return {status:410,body:{code:'editor_session_expired'}};
 if(loseClose){loseClose=false;expired=true;recoveryPhase='working';throw Error('lost close')}
 return {status:200,body:{kind:'closed',registry_id:id(1),document_id:doc,session_id:id(3),mode:'checkpoint',checkpoint_revision:'3'}};};
const factory=v=>{local=structuredClone(v);return {editor:{start:()=>{},stop:()=>{},status:()=>({busy:editorBusy,canRetry:false,canEdit:!editorBusy}),snapshot:()=>structuredClone(local),checkpoint:async()=>{checkpointCalls++;if(checkpointFail)throw Error('failed');local.command_sequence='1';local.checkpoint_revision='2';local.observed_checkpoint_revision='2';return structuredClone(local)},edit:async()=>{}},analysis:{stop:async()=>{},status:()=>({busy:false,canStop:false,canRetryAdmission:false,canRetrySave:false}),dispose:()=>{}},review:{status:()=>({busy:false,canRetry:false}),dispose:()=>{}}}};
const workspace=createDocumentWorkspace({send,createClient:factory,makeId:()=>id(serial++)});assert.equal(calls.length,0);
if(name==='connected'){
 const {createConnectedWorkspace}=await import(pathToFileURL(root+'/src/ara/desktop/client/document-workspace.mjs'));
 const w=createConnectedWorkspace({origin:'http://127.0.0.1:19876',sessionToken:'a'.repeat(64)});assert.deepEqual(w.status().tabs,[]);
 assert.throws(()=>createConnectedWorkspace({origin:'https://example.org',sessionToken:'a'.repeat(64)}));
}else if(name==='preview_close'){recoveryPhase='working';await workspace.open(doc);await workspace.close(doc);assert.equal(workspace.status().tabs.length,0);assert.equal(opened,0);}
else if(name==='foreign'){await assert.rejects(workspace.open(doc));assert.equal(workspace.status().tabs[0].phase,'open_uncertain');}
else if(name==='recover'){recoveryPhase='working';await workspace.open(doc);assert.equal(opened,0);assert.equal(workspace.status().tabs[0].phase,'recovery_required');await workspace.open(doc,{recover:true});assert.equal(JSON.parse(calls.at(-1).body).mode,'recover');}
else if(name==='pending'){recoveryPhase='pending';await workspace.open(doc,{recover:true});assert.equal(workspace.status().tabs[0].phase,'recovery_pending');await workspace.reconcile(doc);assert.equal(workspace.status().tabs[0].phase,'open');}
else if(name==='open_retry'){loseOpen=true;await assert.rejects(workspace.open(doc));const request=calls.at(-1);await workspace.retryOpen(doc);assert.deepEqual(calls.at(-1),request);assert.equal(workspace.status().tabs.length,1);}
else{
 const result=await workspace.open(doc);assert.equal(result.opening,false);
 if(name==='guard'){const actor=workspace.client(doc).editor;loseClose=true;await assert.rejects(workspace.close(doc));assert.throws(()=>actor.edit({action:'undo'}),e=>e.code==='busy');}
 else if(name==='open'){assert.equal(typeof workspace.client(doc).analysis.stop,'function');assert.equal(workspace.client(doc).editor.stop,undefined);const n=calls.length;await workspace.open(doc);workspace.focus(doc);assert.equal(calls.length,n);assert.equal(workspace.status().activeDocumentId,doc);}
 else if(name==='checkpoint_failure'){checkpointFail=true;await assert.rejects(workspace.close(doc));assert.equal(workspace.status().tabs[0].phase,'open');assert.equal(calls.filter(x=>x.path.endsWith('/close')).length,0);}
 else if(name==='busy'){editorBusy=true;await assert.rejects(workspace.close(doc));assert.equal(checkpointCalls,0);}
 else if(name==='close_retry'||name==='close_unproven'){loseClose=true;await assert.rejects(workspace.close(doc));const request=calls.at(-1);prove=name==='close_retry';if(prove)await workspace.retryClose(doc);else await assert.rejects(workspace.retryClose(doc));assert.deepEqual(calls.at(-2),request);assert.equal(workspace.status().tabs.length,prove?0:1);}
 else throw Error(name);
}
console.log('ok '+name);
