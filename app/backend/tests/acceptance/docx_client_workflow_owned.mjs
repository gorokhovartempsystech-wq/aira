import assert from 'node:assert/strict';import {pathToFileURL} from 'node:url';
let input='';for await(const chunk of process.stdin)input+=chunk;const job=JSON.parse(input);input='';
const module=n=>import(pathToFileURL(job.root+'/src/ara/desktop/client/'+n+'.mjs'));
const {createConnectedWorkspace}=await module('document-workspace');
const {createConnectedImporter}=await module('docx-files');
const host={origin:job.origin,sessionToken:job.token};
const realSet=globalThis.setTimeout,realClear=globalThis.clearTimeout,autosaves=new Map();
globalThis.setTimeout=(fn,ms,...args)=>{if(ms!==120000)return realSet(fn,ms,...args);const key=Symbol('autosave');autosaves.set(key,()=>fn(...args));return key};
globalThis.clearTimeout=key=>{if(typeof key==='symbol')autosaves.delete(key);else realClear(key)};
const sleep=ms=>new Promise(resolve=>realSet(resolve,ms));
async function until(predicate,label,ms=90000){const end=Date.now()+ms;while(!predicate()){assert.ok(Date.now()<end,typeof label==='function'?label():label);await sleep(20)}}
const w=createConnectedWorkspace(host),importer=createConnectedImporter(host);
async function checked(client){await client.analysis.check();await until(()=>client.analysis.status().phase==='finished','analysis did not finish');
 const receipt=client.analysis.status().receipt;assert.equal(receipt.fixture,true);assert.equal(receipt.state.status,'succeeded');
 await client.review.load(receipt.run_id);assert.equal(client.review.status().canHighlight,true);assert.equal(client.review.status().review.fixture,true);return receipt;}
try{
 if(job.mode==='draft'){
  const documents=[await importer.create('Новый документ AIRA')];
  for(const [i,raw]of job.sources.entries())documents.push(await importer.importDocx('Контрольный DOCX '+i,new Uint8Array(Buffer.from(raw,'base64'))));
  let firstRun,hidden;
  for(const [i,d]of documents.entries()){
   await w.open(d.document_id);const c=w.client(d.document_id),before=c.editor.snapshot().document.source_sha256;
   await c.editor.edit({action:'insert_text',value:'Сценарий 🧪 '});const edited=c.editor.snapshot().document.source_sha256;assert.notEqual(before,edited);
   await c.editor.edit({action:'undo'});assert.equal(c.editor.snapshot().document.source_sha256,before);
   await c.editor.edit({action:'redo'});assert.equal(c.editor.snapshot().document.source_sha256,edited);
   if(i===0){const receipt=await checked(c);firstRun=receipt.run_id;const finding=c.review.status().review.view.findings[0];hidden=finding.finding_id;
    await c.review.setHidden(hidden,true);assert.equal(c.review.status().review.view.no_visible_findings,true);
    await c.review.setFilters({disabled_types:[],show_questions:false,show_hidden:false});assert.equal(c.review.status().review.view.questions.length,0);
    await c.editor.edit({action:'insert_text',value:'Черновик '});assert.equal(c.review.status().stale,true);
   }
  }
  assert.equal(w.status().tabs.length,3);w.focus(documents[0].document_id);assert.equal(w.status().activeDocumentId,documents[0].document_id);
  const revisions=documents.map(d=>w.metadata(d.document_id).checkpoint_revision);assert.equal(autosaves.size,3);
  for(const [key,fn]of [...autosaves]){autosaves.delete(key);fn()}
  await until(()=>documents.every(d=>{const s=w.client(d.document_id).editor.status();return !s.uncheckpointed&&!s.busy}),()=>JSON.stringify(documents.map(d=>w.client(d.document_id).editor.status())),15000);
  for(const [i,d]of documents.entries())assert.ok(BigInt(w.metadata(d.document_id).checkpoint_revision)>BigInt(revisions[i]));
  await w.closeAll();assert.equal(w.status().tabs.length,0);assert.equal(autosaves.size,0);
  process.stdout.write(JSON.stringify({documents:documents.map(d=>({document_id:d.document_id,title:d.title})),firstRun,hidden,fixture:true}));
 }else{
  const exports=[];let reopened=0;
  for(const [i,d]of job.state.documents.entries()){
   await w.open(d.document_id);assert.equal(w.status().tabs.find(t=>t.documentId===d.document_id).phase,'recovery_required');
   await w.open(d.document_id,{recover:true});const c=w.client(d.document_id);assert.equal(c.editor.snapshot().document.is_dirty,true);
   if(i===0){await c.review.load(job.state.firstRun);assert.equal(c.review.status().stale,true);assert.ok(c.review.status().review.view.hidden_finding_ids.includes(job.state.hidden));
    assert.equal(c.review.status().review.preferences.show_questions,false);
    await c.review.setFilters({disabled_types:[],show_questions:true,show_hidden:true});assert.ok(c.review.status().review.view.findings.some(x=>x.finding_id===job.state.hidden));
    await c.review.setHidden(job.state.hidden,false);await c.review.setFilters({disabled_types:[],show_questions:true,show_hidden:false});}
   await checked(c);const finding=c.review.status().review.view.findings[0];
   await c.review.setFilters({disabled_types:[finding.type],show_questions:false,show_hidden:false});assert.equal(c.review.status().review.view.no_visible_findings,true);
   await c.review.setFilters({disabled_types:[],show_questions:true,show_hidden:false});
   await c.editor.edit({action:'insert_text',value:'Финал '});assert.equal(c.review.status().stale,true);
   await checked(c);const result=await c.files.exportDocx();assert.equal(result.sha256,c.editor.snapshot().document.source_sha256);
   exports.push({documentId:d.document_id,sha256:result.sha256,data:Buffer.from(result.bytes).toString('base64')});
   const imported=await importer.importDocx('Повторное открытие '+i,result.bytes);assert.equal(imported.current_sha256,result.sha256);
   await w.open(imported.document_id);assert.equal(w.client(imported.document_id).editor.snapshot().document.source_sha256,result.sha256);reopened++;
  }
  await w.closeAll();assert.equal(w.status().tabs.length,0);assert.equal(autosaves.size,0);
  process.stdout.write(JSON.stringify({exports,reopened,fixture:true}));
 }
}finally{globalThis.setTimeout=realSet;globalThis.clearTimeout=realClear}
