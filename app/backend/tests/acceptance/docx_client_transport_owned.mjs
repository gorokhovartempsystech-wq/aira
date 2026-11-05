// Synthetic owned integration only; the ephemeral capability arrives on stdin, never argv/log.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
let input='';for await(const chunk of process.stdin)input+=chunk;
const job=JSON.parse(input);input='';
const {createEditorTransport}=await import(pathToFileURL(job.root+'/src/ara/desktop/client/editor-transport.mjs'));
const {createDocxSession}=await import(pathToFileURL(job.root+'/src/ara/desktop/client/docx-session.mjs'));
const options={origin:job.origin,sessionToken:job.token,documentId:job.view.document_id,sessionId:job.view.session_id};
const transport=createEditorTransport(options),calls=[];let lose=job.mode==='checkpoint';
const timers=new Map();let serial=0;
const client=createDocxSession({view:job.view,send:async request=>{
 calls.push(request);const reply=await transport(request);
 if(lose){lose=false;throw Error('synthetic lost response after backend acknowledgement')}
 return reply;
},schedule:(fn,ms)=>{assert.equal(ms,120000);timers.set(++serial,fn);return serial},cancel:id=>timers.delete(id)});
client.start();
if(job.mode==='checkpoint'){
 const denied=createEditorTransport({...options,sessionToken:'0'.repeat(64)});
 const path=`/docx-documents/${job.view.document_id}/editor-sessions/${job.view.session_id}/commands`;
 const body=JSON.stringify({command_id:crypto.randomUUID(),expected_command_sequence:job.view.command_sequence,expected_session_revision:job.view.document.session_revision,command:{action:'insert_text',value:'MUST_NOT_APPEAR'}});
 assert.equal((await denied({path,body})).status,403);
 await assert.rejects(client.edit({action:'insert_text',value:'Автосохранение 🧪 '}));
 assert.equal(client.snapshot().command_sequence,job.view.command_sequence);
 assert.equal(client.status().canEdit,false);await client.retry();
 assert.deepEqual(calls[0],calls[1]);assert.equal(client.snapshot().command_sequence,'1');
 assert.equal(timers.size,1);const timer=[...timers.values()][0];timers.clear();timer();
 const end=Date.now()+45000;
 while(client.status().busy||client.snapshot().command_sequence!=='2'){
  assert.ok(Date.now()<end,'checkpoint did not finish');await new Promise(resolve=>setTimeout(resolve,5));
 }
 assert.equal(client.snapshot().document.is_dirty,true);assert.equal(client.status().uncheckpointed,false);
 assert.equal(calls.length,3);assert.ok(calls[2].path.endsWith('/checkpoint'));
}else{
 assert.equal(job.mode,'save');assert.equal(client.status().dirty,true);
 const saved=await client.save();assert.equal(saved.document.is_dirty,false);
 assert.equal(client.status().uncheckpointed,false);assert.equal(calls.length,1);
}
client.stop();assert.equal(timers.size,0);process.stdout.write(JSON.stringify(client.snapshot()));
