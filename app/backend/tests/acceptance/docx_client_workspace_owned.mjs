import assert from 'node:assert/strict';import {pathToFileURL} from 'node:url';
let input='';for await(const c of process.stdin)input+=c;const job=JSON.parse(input);input='';
const module=n=>import(pathToFileURL(job.root+'/src/ara/desktop/client/'+n+'.mjs'));
const {createDocumentWorkspace}=await module('document-workspace'),{createWorkspaceTransport}=await module('workspace-transport');
const {createEditorTransport}=await module('editor-transport'),{createDocxSession}=await module('docx-session');
const {createAnalysisSession}=await module('analysis-session'),{createAnalysisTransport}=await module('analysis-transport');
const {createReviewSession}=await module('review-session'),{createReviewTransport}=await module('review-transport');
const host={origin:job.origin,sessionToken:job.token},transport=createWorkspaceTransport(host);
let loseOpen=job.mode==='draft',loseClose=job.mode==='draft';const writes=[];
const workspace=createDocumentWorkspace({send:async req=>{const r=await transport(req);if(req.method==='POST')writes.push({...req});
 if(loseOpen&&req.path.endsWith('/editor-sessions')){loseOpen=false;throw Error('lost open')}
 if(loseClose&&req.path.endsWith('/close')){loseClose=false;throw Error('lost close')};return r;
},createClient:view=>{const o={...host,documentId:view.document_id};const editor=createDocxSession({view,send:createEditorTransport({...o,sessionId:view.session_id})});return {editor,analysis:createAnalysisSession({documentId:view.document_id,editor,send:createAnalysisTransport(o)}),review:createReviewSession({documentId:view.document_id,editor,send:createReviewTransport(o)})}}});
const saved=[];
for(const [i,documentId]of job.documents.entries()){
 if(job.mode==='draft'){
  if(i===0){await assert.rejects(workspace.open(documentId));await workspace.retryOpen(documentId);assert.deepEqual(writes[0],writes[1]);}
  else await workspace.open(documentId);
  const c=workspace.client(documentId);await c.editor.edit({action:'insert_text',value:'Вкладка 🧪 '});
  if(i===0){await c.analysis.check();const end=Date.now()+90000;while(c.analysis.status().phase!=='finished'){assert.ok(Date.now()<end);await new Promise(r=>setTimeout(r,20));}assert.equal(c.analysis.status().receipt.state.status,'succeeded');await c.review.load();await c.editor.edit({action:'insert_text',value:'Черновик '});}
 }else{
  await workspace.open(documentId);assert.equal(workspace.status().tabs.find(t=>t.documentId===documentId).phase,'recovery_required');
  await workspace.open(documentId,{recover:true});const c=workspace.client(documentId);assert.equal(c.editor.snapshot().document.is_dirty,true);
  if(i===0){await c.review.load();assert.equal(c.review.status().stale,true);}
  await c.editor.save();saved.push(c.editor.snapshot());
 }
}
assert.equal(workspace.status().tabs.length,2);workspace.focus(job.documents[0]);
if(job.mode==='draft'){
 await assert.rejects(workspace.close(job.documents[0]));const close=writes.at(-1);await workspace.retryClose(job.documents[0]);assert.deepEqual(writes.at(-1),close);
 assert.equal(workspace.status().tabs.length,1);await workspace.close(job.documents[1]);
}else await workspace.closeAll();
assert.equal(workspace.status().tabs.length,0);process.stdout.write(JSON.stringify({saved}));
