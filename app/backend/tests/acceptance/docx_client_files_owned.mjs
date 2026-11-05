import assert from 'node:assert/strict';import {pathToFileURL} from 'node:url';
let input='';for await(const c of process.stdin)input+=c;const job=JSON.parse(input);input='';
const module=n=>import(pathToFileURL(job.root+'/src/ara/desktop/client/'+n+'.mjs'));
const {createDocxImporter}=await module('docx-files'),{createFileTransport}=await module('file-transport');
const {createConnectedWorkspace}=await module('document-workspace');
const host={origin:job.origin,sessionToken:job.token},port=createFileTransport(host);let loseImport=true;
const uploads=[];const importer=createDocxImporter({send:async req=>{const response=await port(req);
 uploads.push({path:req.path,body:req.body?Buffer.from(req.body).toString('base64'):null});
 if(loseImport&&req.path.includes('/import?')){loseImport=false;throw Error('lost import')};return response;}});
const documents=[await importer.create('Новый документ')];
for(const [i,raw]of job.sources.entries()){
 if(i===0){await assert.rejects(importer.importDocx('Импорт '+i,new Uint8Array(Buffer.from(raw,'base64'))));documents.push(await importer.retry());assert.deepEqual(uploads[1],uploads[2])}
 else documents.push(await importer.importDocx('Импорт '+i,new Uint8Array(Buffer.from(raw,'base64'))));
}
const originalFetch=globalThis.fetch;let loseSave=true,loseDownload=true;const saves=[],downloads=[];
globalThis.fetch=async(url,opts)=>{const response=await originalFetch(url,opts);
 if(url.endsWith('/save')){saves.push(opts.body);if(loseSave){loseSave=false;await response.arrayBuffer();throw Error('lost save')}}
 if(url.endsWith('/saved-content')){downloads.push(opts.body);if(loseDownload){loseDownload=false;await response.arrayBuffer();throw Error('lost download')}}
 return response;};
const w=createConnectedWorkspace(host),outputs=[];
try{
 for(const [i,d]of documents.entries()){
  await w.open(d.document_id);const c=w.client(d.document_id);await c.editor.edit({action:'insert_text',value:'Экспорт 🧪 '});let exported;
  if(i===0){await assert.rejects(c.files.exportDocx());assert.throws(()=>c.editor.edit({action:'undo'}));await assert.rejects(c.files.retry());exported=await c.files.retry();assert.equal(saves[0],saves[1]);assert.equal(downloads[0],downloads[1])}
  else exported=await c.files.exportDocx();
  assert.equal(c.editor.snapshot().document.is_dirty,false);assert.equal(exported.sha256,c.editor.snapshot().document.source_sha256);
  outputs.push({document_id:d.document_id,filename:exported.filename,data:Buffer.from(exported.bytes).toString('base64')});
 }
 await w.closeAll();process.stdout.write(JSON.stringify(outputs));
}finally{globalThis.fetch=originalFetch;}
