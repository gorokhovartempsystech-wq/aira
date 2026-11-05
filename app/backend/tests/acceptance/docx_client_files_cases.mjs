import assert from 'node:assert/strict';import {pathToFileURL} from 'node:url';
const root=process.argv[2],name=process.argv[3];
const module=n=>import(pathToFileURL(root+'/src/ara/desktop/client/'+n+'.mjs'));
const {createDocxImporter,createDocxExporter}=await module('docx-files');
const {createFileTransport,DOCX_MIME,MAX_DOCX_BYTES}=await module('file-transport');
const id=n=>'00000000-0000-0000-0000-'+String(n).padStart(12,'0'),hash='a'.repeat(64),doc=id(2);
function view(){const caret={anchor:{source_sha256:hash,part_name:'word/document.xml',path:[0,0]},offset:0,affinity:'right'};return {kind:'editor',registry_id:id(1),document_id:doc,session_id:id(3),command_sequence:'0',base_storage_revision:'1',base_sha256:hash,checkpoint_revision:'1',observed_current:{document_id:doc,storage_revision:'1',current_sha256:hash},observed_checkpoint_revision:'1',observed_checkpoint_phase:'empty',state:'editable',recovery_operation_id:null,last_command:null,active_command:null,position_id:'0',selection:{anchor:caret,focus:caret},document:{session_revision:'0',source_sha256:hash,main_part:'word/document.xml',is_dirty:false,undo_depth:0,redo_depth:0}}}

const bytes=new Uint8Array([1,2,3]),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
const metadata={document_id:doc,title:'Тест 🧪',storage_revision:name==='unsafe_revision'?Number.MAX_SAFE_INTEGER+1:1,current_sha256:hash,current_size_bytes:3};
const calls=[];let lose=false,foreign=false;
const importer=createDocxImporter({makeId:()=>doc,send:async req=>{calls.push({...req,body:req.body instanceof Uint8Array?new Uint8Array(req.body):req.body});if(lose){lose=false;throw Error('lost')};return {status:200,body:{...metadata,document_id:foreign?id(99):doc}}}});
if(['create','import_copy','metadata','invalid_input','unsafe_revision'].includes(name)){
 if(name==='create'){lose=true;await assert.rejects(importer.create(metadata.title));await importer.retry();assert.deepEqual(calls[0],calls[1]);assert.equal(calls[0].body,undefined);assert.equal(importer.status().pending,false)}
 if(name==='import_copy'){lose=true;const source=new Uint8Array(bytes);await assert.rejects(importer.importDocx(metadata.title,source));source.fill(9);await importer.retry();assert.deepEqual(calls[0],calls[1]);assert.deepEqual(calls[1].body,bytes)}
 if(name==='unsafe_revision'){await assert.rejects(importer.create(metadata.title));assert.equal(importer.status().pending,true)}
 if(name==='metadata'){foreign=true;await assert.rejects(importer.create(metadata.title));assert.equal(importer.status().pending,true)}
 if(name==='invalid_input'){for(const t of ['', ' ', '\u0000','x'.repeat(201),'\ud800'])await assert.rejects(importer.create(t));assert.equal(calls.length,0);await assert.rejects(importer.importDocx('Test',new Uint8Array(MAX_DOCX_BYTES+1)));}
}else if(name.startsWith('transport_')){
 const origin='http://127.0.0.1:19876',path=`/docx-documents/${doc}/editor-sessions/${id(3)}/saved-content`;let callback,fetchCalls=0;
 const port=createFileTransport({origin,sessionToken:'a'.repeat(64),schedule:fn=>{callback=fn;return 1},cancel:()=>{},fetchImpl:async(url,opts)=>{
  fetchCalls++;calls.push({url,opts});if(name==='transport_timeout')return new Promise(()=>{});
  const create=name==='transport_create';const body=create?new TextEncoder().encode(JSON.stringify(metadata)):bytes;
  return {status:200,url:name==='transport_foreign'?'https://example.org':url,redirected:false,type:'basic',headers:new Headers({
   'Content-Type':name==='transport_media'?'application/pdf':create?'application/json':DOCX_MIME,
   'Content-Length':name==='transport_limit'?String(MAX_DOCX_BYTES+1):String(body.length),
   ETag:'"'+(name==='transport_hash'?hash:sha)+'"','X-ARA-Copy-Kind':name==='transport_copy_kind'?'working':'saved','X-ARA-Storage-Revision':name==='transport_revision'?'0':'1'}),
   body:new ReadableStream({start(c){c.enqueue(body);c.close()}})};
 }});
 const req=name==='transport_create'?{path:`/docx-documents/${doc}/create?title=${encodeURIComponent(metadata.title)}`}:{path,body:'{}'};
 if(name==='transport_timeout'){const promise=port(req);callback();await assert.rejects(promise,e=>e.code==='transport_error')}
 else if(['transport_hash','transport_media','transport_limit','transport_foreign','transport_copy_kind','transport_revision'].includes(name))await assert.rejects(port(req));
 else {const result=await port(req);if(name==='transport_create'){assert.deepEqual(result.body,metadata);assert.equal(calls[0].opts.headers['Content-Type'],undefined);assert.equal(calls[0].opts.body,undefined)}else {assert.deepEqual(result.bytes,bytes);assert.equal(result.sha256,sha)}}
 assert.equal(fetchCalls,1);await assert.rejects(port({path:'https://example.org',body:'{}'}));assert.equal(fetchCalls,1);
}else{
 let v=view(),saveCount=0,pendingSave=false,downloadCount=0,release;
 const editor={status:()=>({busy:false,canRetry:pendingSave,canEdit:!pendingSave}),snapshot:()=>structuredClone(v),start(){},stop(){},edit(){},
  async save(){saveCount++;if(['save_retry','cancel_save'].includes(name)&&!pendingSave){pendingSave=true;throw Error('lost save')};return saved()},
  async retry(){pendingSave=false;return saved()},checkpoint:async()=>v};
 function saved(){v.command_sequence='1';v.last_command={command_id:id(8),request_sha256:hash,action:'save',expected_command_sequence:'0',expected_session_revision:'0',result_command_sequence:'1',result_session_revision:'0',result_position_id:'0'};return structuredClone(v)}
 const send=async req=>{calls.push({...req});downloadCount++;assert.equal(v.last_command.action,'save');if(['download_retry','cancel','workspace_guard'].includes(name)&&downloadCount===1)throw Error('lost download');return {status:200,bytes,sha256:name==='wrong_copy'?'b'.repeat(64):hash,storageRevision:name==='wrong_revision'?'2':'1',copyKind:'saved'}};
 const files=createDocxExporter({documentId:doc,editor,send});
 if(name==='cancel_save'){await assert.rejects(files.exportDocx());assert.throws(()=>files.cancel());assert.equal(files.status().pending,true)}
 else if(name==='save_retry'){await assert.rejects(files.exportDocx());assert.equal(downloadCount,0);await files.retry();assert.equal(saveCount,1);assert.equal(downloadCount,1)}
 else if(name==='download_retry'){await assert.rejects(files.exportDocx());await files.retry();assert.deepEqual(calls[0],calls[1]);assert.equal(saveCount,1)}
 else if(['wrong_copy','wrong_revision'].includes(name)){await assert.rejects(files.exportDocx());assert.equal(files.status().pending,true)}
 else if(name==='cancel'){await assert.rejects(files.exportDocx());files.cancel();assert.equal(files.status().pending,false)}
 else if(name==='workspace_guard'){
  const {createDocumentWorkspace}=await module('document-workspace');const clients={editor,files,analysis:{status:()=>({}),check(){},stop(){return 'stopped'},dispose(){}},review:{status:()=>({}),dispose(){}}};
  const w=createDocumentWorkspace({makeId:()=>id(7),createClient:()=>clients,send:async req=>req.method==='GET'?{status:200,body:{kind:'recovery',registry_id:id(1),open_sequence:'0',checkpoint_revision:'0',phase:'empty',document:{document_id:doc,current_sha256:hash}}}:{status:200,body:{kind:'opened',accepted_open_sequence:'0',next_open_sequence:'1',view:view()}}});
  await w.open(doc);const c=w.client(doc);await assert.rejects(c.files.exportDocx());assert.throws(()=>c.editor.edit({action:'undo'}),e=>e.code==='busy');assert.throws(()=>c.analysis.check(),e=>e.code==='busy');await assert.rejects(w.close(doc));assert.equal(c.analysis.stop(),'stopped');c.files.cancel();c.editor.edit({action:'undo'});
 }else {const result=await files.exportDocx();assert.equal(result.filename,doc+'.docx');assert.deepEqual(result.bytes,bytes);assert.equal(saveCount,1);assert.equal(JSON.parse(calls[0].body).expected_command_sequence,'1');assert.equal(files.status().pending,false)}
}
console.log('ok '+name);
