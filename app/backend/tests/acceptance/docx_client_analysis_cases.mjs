import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const root=process.argv[2], name=process.argv[3];
const {createAnalysisSession}=await import(pathToFileURL(root+'/src/ara/desktop/client/analysis-session.mjs'));
const uid=n=>'00000000-0000-0000-0000-'+String(n).padStart(12,'0');
const doc=uid(1), digest='a'.repeat(64), timers=new Map();let serial=0,id=100;
let saves=0, retries=0, failSave=false, failPost=false, hold=null;
const saved={document_id:doc,registry_id:uid(2),session_id:uid(3),command_sequence:'2',base_storage_revision:'3',base_sha256:digest,document:{session_revision:'1',source_sha256:digest,is_dirty:false},last_command:{action:'save',command_id:uid(4)}};
const editor={save:async()=>{saves++;if(failSave)throw Error('synthetic');return structuredClone(saved)},retry:async()=>{retries++;return structuredClone(saved)},status:()=>({canRetry:failSave})};
const calls=[];
function receipt(key, status=null){return {schema_version:'docx-analysis-http/1',document_id:doc,client_request_id:key,phase:status?'finished':'admitting',run_id:status?uid(5):null,stop_requested:false,stop_reason:null,error_code:null,fixture:true,state:status?{document_id:doc,client_request_id:key,run_id:uid(5),source_sha256:digest,storage_revision:'3',status,execution_kind:'fixture'}:null}}
let key;
const send=async req=>{calls.push({...req});if(hold)return await hold(req);if(req.method==='POST'&&!req.path.endsWith('/stop')){key=JSON.parse(req.body).client_request_id;if(failPost){failPost=false;throw Error('lost response')};return {status:202,body:receipt(key)}}return {status:200,body:receipt(key,'succeeded')}};
const client=createAnalysisSession({documentId:doc,editor,send,makeId:()=>uid(id++),schedule:(fn,ms)=>{assert.equal(ms,250);timers.set(++serial,fn);return serial},cancel:t=>timers.delete(t)});
assert.equal(saves,0);assert.equal(calls.length,0);assert.equal(timers.size,0);
if(name==='save'){
 await client.check();assert.equal(saves,1);assert.equal(JSON.parse(calls[0].body).save_command_id,uid(4));await client.refresh();assert.equal(client.status().receipt.state.status,'succeeded');assert.equal(timers.size,0);
}else if(name==='save_retry'){
 failSave=true;await assert.rejects(client.check());assert.equal(calls.length,0);await client.retrySave();assert.equal(retries,1);assert.equal(saves,1);assert.equal(calls.length,1);
}else if(name==='admission_retry'){
 failPost=true;await assert.rejects(client.check());await client.retryAdmission();assert.deepEqual(calls[0],calls[1]);assert.equal(saves,1);
}else if(name==='double'){
 let release;editor.save=()=>{saves++;return new Promise(r=>release=r)};const pending=client.check();await assert.rejects(client.check());release(saved);await pending;assert.equal(saves,1);assert.equal(calls.length,1);
}else if(name==='foreign'){
 hold=async req=>({status:202,body:{...receipt(JSON.parse(req.body).client_request_id),document_id:uid(99)}});await assert.rejects(client.check());assert.equal(client.status().phase,'admission_uncertain');
}else if(name==='stop'){
 await client.check();let release;
 hold=async req=>req.path.endsWith('/stop')?{status:202,body:{...receipt(key,'cancelled'),stop_requested:true}}:await new Promise(r=>release=r);
 const polling=client.refresh();await client.stop();release({status:200,body:receipt(key)});await polling;assert.equal(client.status().receipt.state.status,'cancelled');assert.equal(client.status().stopRequested,true);
}else if(name==='dispose'){
 let release;editor.save=()=>new Promise(r=>release=r);const pending=client.check();client.dispose();release(saved);await assert.rejects(pending);assert.equal(calls.length,0);assert.equal(timers.size,0);
}else if(name==='old_retry'){
 await client.check();await client.refresh();await client.retryAnalysis();assert.equal(saves,1);assert.ok(calls.at(-1).path.endsWith('/'+uid(5)+'/retry'));assert.deepEqual(Object.keys(JSON.parse(calls.at(-1).body)),['client_request_id']);
 }else if(name==='source_mismatch'){
 await client.check();hold=async()=>{const r=receipt(key,'succeeded');r.state.source_sha256='b'.repeat(64);return {status:200,body:r}};
 await assert.rejects(client.refresh());assert.equal(client.status().phase,'poll_error');assert.equal(client.status().receipt.state,null);
}else if(name==='poll_retry'){
 await client.check();hold=async()=>{throw Error('synthetic')};await assert.rejects(client.refresh());hold=null;
 assert.equal(client.status().canRetryAdmission,true);await client.retryAdmission();assert.deepEqual(calls[0],calls[2]);
}else if(name==='callback_timer'){
 const c=createAnalysisSession({documentId:doc,editor,send,makeId:()=>uid(id++),schedule:()=>{throw Error('synthetic')},onState:()=>{throw Error('synthetic')}});
 await c.check();assert.equal(c.status().phase,'poll_error');await c.refresh();assert.equal(c.status().receipt.state.status,'succeeded');c.dispose();
}else if(name==='late_stop'){
 await client.check();let release;hold=async req=>req.path.endsWith('/stop')?await new Promise(r=>release=r):{status:200,body:receipt(key,'succeeded')};
 const stopping=client.stop();await client.refresh();release({status:202,body:receipt(key)});await stopping;assert.equal(client.status().receipt.state.status,'succeeded');
}else if(name==='transport'){
 const {createAnalysisTransport}=await import(pathToFileURL(root+'/src/ara/desktop/client/analysis-transport.mjs'));
 const origin='http://127.0.0.1:19876',token='a'.repeat(64),prefix='/docx-documents/'+doc+'/';let finish;const seen=[];
 const transport=createAnalysisTransport({origin,sessionToken:token,documentId:doc,fetchImpl:async(url,opts)=>{seen.push([url,opts]);if(opts.method==='GET')await new Promise(r=>finish=r);return {status:200,url,redirected:false,type:'basic',headers:new Headers({'Content-Type':'application/json'}),body:new Response('{}').body}}});
 await assert.rejects(transport({path:prefix+'analysis-result',method:'GET'}));
 const pending=transport({path:prefix+'analysis-requests/'+uid(8),method:'GET'});
 await transport({path:prefix+'analysis-requests/'+uid(8)+'/stop',method:'POST',body:'{}'});finish();await pending;assert.equal(seen.length,2);assert.equal(seen[0][1].redirect,'error');assert.equal(seen[0][1].headers['X-AIRA-Session'],token);
}else throw Error(name);
client.dispose();assert.equal(timers.size,0);console.log('ok '+name);
