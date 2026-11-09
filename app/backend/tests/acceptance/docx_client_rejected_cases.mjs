import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const root=process.argv[2], mode=process.argv[3];
const {createAnalysisSession}=await import(pathToFileURL(root+'/src/ara/desktop/client/analysis-session.mjs'));
const {createDocumentWorkspace}=await import(pathToFileURL(root+'/src/ara/desktop/client/document-workspace.mjs'));
const id=n=>'00000000-0000-0000-0000-'+String(n).padStart(12,'0'),doc=id(2),hash='a'.repeat(64);
const caret={anchor:{source_sha256:hash,part_name:'word/document.xml',path:[0,0]},offset:0,affinity:'right'};
let view={kind:'editor',registry_id:id(1),document_id:doc,session_id:id(3),command_sequence:'0',base_storage_revision:'1',base_sha256:hash,checkpoint_revision:'1',observed_current:{document_id:doc,storage_revision:'1',current_sha256:hash},observed_checkpoint_revision:'1',observed_checkpoint_phase:'empty',state:'editable',recovery_operation_id:null,last_command:null,active_command:null,position_id:'0',selection:{anchor:caret,focus:caret},document:{session_revision:'0',source_sha256:hash,main_part:'word/document.xml',is_dirty:false,undo_depth:0,redo_depth:0}};
let key,seq=100,saves=0,checkpoints=0,exports=0,edits=0,hold=null;const calls=[],timers=new Map();
const editor={start(){},stop(){},status:()=>({canEdit:true,busy:false,canRetry:false}),snapshot:()=>structuredClone(view),
 async edit(){edits++},async save(){saves++;view.command_sequence=String(saves);view.last_command={action:'save',command_id:id(seq++),request_sha256:hash,expected_command_sequence:String(saves-1),expected_session_revision:'0',result_command_sequence:String(saves),result_session_revision:'0',result_position_id:'0'};return structuredClone(view)},async retry(){throw Error('unexpected retry')},async checkpoint(){checkpoints++;return structuredClone(view)}};
const receipt=(phase='not_admitted')=>({schema_version:'docx-analysis-http/1',document_id:doc,client_request_id:key,phase,run_id:null,state:null,fixture:true,stop_requested:false,error_code:'unsupported_analysis_content',stop_reason:null});
const send=async req=>{calls.push(req);if(req.method==='POST'&&!req.path.endsWith('/stop'))key=JSON.parse(req.body).client_request_id;if(hold)return hold(req);return {status:req.method==='GET'?200:202,body:receipt()}};
const analysis=createAnalysisSession({documentId:doc,editor,send,makeId:()=>id(seq++),schedule:fn=>{const k=seq++;timers.set(k,fn);return k},cancel:k=>timers.delete(k)});
if(mode==='workspace'){
 const workspace=createDocumentWorkspace({makeId:()=>id(seq++),send:async req=>{
  if(req.method==='GET')return {status:200,body:{kind:'recovery',registry_id:id(1),open_sequence:'0',document:{document_id:doc,current_sha256:hash},checkpoint_revision:'1',phase:'empty',working_sha256:null}};
  if(req.path.endsWith('/editor-sessions'))return {status:200,body:{kind:'opened',view,accepted_open_sequence:'0',next_open_sequence:'1'}};
  return {status:200,body:{kind:'closed',registry_id:id(1),document_id:doc,session_id:id(3),mode:'checkpoint',checkpoint_revision:'2'}};
 },createClient:()=>({editor,analysis,review:{status:()=>({busy:false,canRetry:false}),dispose(){}},files:{status:()=>({busy:false,pending:false}),async exportDocx(){exports++;return 'saved'}}})});
 await workspace.open(doc);const c=workspace.client(doc);await c.analysis.check();await c.editor.edit();assert.equal(await c.files.exportDocx(),'saved');await workspace.closeAll();assert.equal(workspace.status().tabs.length,0);assert.equal(checkpoints,1);assert.equal(exports,1);assert.equal(edits,1);
}else if(mode==='rejected'){
 await analysis.check();const s=analysis.status();assert.equal(s.phase,'not_admitted');assert.equal(s.receipt.error_code,'unsupported_analysis_content');assert.equal(s.canStop,false);assert.equal(s.canRetryAdmission,false);assert.equal(s.canCheck,true);assert.equal(timers.size,0);
 await assert.rejects(analysis.stop());await assert.rejects(analysis.retryAdmission());const count=calls.length;await analysis.refresh();assert.equal(calls.length,count);
 const old=key;await analysis.check();assert.notEqual(key,old);assert.equal(saves,2);
}else if(mode==='uncertain'){
 hold=async()=>{throw Error('response lost')};await assert.rejects(analysis.check());const s=analysis.status();assert.equal(s.canCheck,false);assert.equal(s.canRetryAdmission,true);assert.equal(s.canStop,true);
}else if(mode==='bound_run'){
 hold=async()=>({status:202,body:{...receipt(),run_id:id(9)}});await analysis.check();assert.equal(analysis.status().canCheck,false);assert.equal(analysis.status().canStop,true);
}else if(mode==='late_poll'||mode==='late_poll_error'){
 hold=async()=>({status:202,body:receipt('admitting')});await analysis.check();let resolve,reject;
 hold=async req=>req.method==='GET'?new Promise((a,b)=>{resolve=a;reject=b}):{status:202,body:receipt()};
 const p=analysis.refresh();await analysis.stop();
 if(mode==='late_poll')resolve({status:200,body:receipt('admitting')});else reject(Error('late failure'));
 if(mode==='late_poll')await p;else await assert.rejects(p);
 assert.equal(analysis.status().phase,'not_admitted');assert.equal(analysis.status().canStop,false);assert.equal(timers.size,0);
}else throw Error(mode);
analysis.dispose();console.log('ok '+mode);
