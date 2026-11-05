import {DocxClientError,requireValue,uuid,copyJson,checkedView} from './protocol.mjs';
import {createFileTransport,checkedTitle,MAX_DOCX_BYTES} from './file-transport.mjs';
const hash=x=>requireValue(typeof x==='string'&&x.length===64&&/^[0-9a-f]{64}$/.test(x),'invalid_response');
const failure=()=>new DocxClientError('request_failed');
function notify(fn,value){try{Promise.resolve(fn(value)).catch(()=>{})}catch(_){}}
export function createDocxImporter({send,makeId=()=>globalThis.crypto.randomUUID(),onState=()=>{}}){
 for(const fn of [send,makeId,onState])requireValue(typeof fn==='function');let pending=null,busy=false,phase='idle';
 function status(){return {phase,busy,pending:pending!==null,canRetry:pending!==null&&!busy,documentId:pending?.id??null}}
 function emit(){notify(onState,status())}
 async function dispatch(){requireValue(pending!==null&&!busy,'busy');busy=true;phase='uploading';emit();const intent=pending;
  try{
   const reply=await send({path:intent.path,...(intent.bytes?{body:new Uint8Array(intent.bytes)}:{})});
   if(!intent.uncertain&&[413,415,422].includes(reply?.status)){pending=null;phase='rejected';throw failure()}
   requireValue(reply?.status===200,'request_failed');const value=copyJson(reply.body);
   requireValue(value.document_id===intent.id&&value.title===intent.title&&Number.isSafeInteger(value.storage_revision)&&value.storage_revision>=1
    &&Number.isSafeInteger(value.current_size_bytes)&&value.current_size_bytes>0&&value.current_size_bytes<=MAX_DOCX_BYTES,'invalid_response');hash(value.current_sha256);
   pending=null;phase='ready';return value;
  }catch(_){if(pending){pending.uncertain=true;phase='uncertain'}throw failure()}
  finally{busy=false;emit()}
 }
 async function begin(kind,title,bytes){requireValue(!pending&&!busy,'busy');checkedTitle(title);
  if(kind==='import')requireValue(bytes instanceof Uint8Array&&bytes.byteLength>0&&bytes.byteLength<=MAX_DOCX_BYTES);
  const id=uuid(makeId());pending={id,title,path:`/docx-documents/${id}/${kind}?title=${encodeURIComponent(title)}`,bytes:kind==='import'?new Uint8Array(bytes):null,uncertain:false};return dispatch();
 }
 return Object.freeze({status,create:title=>begin('create',title),importDocx:(title,bytes)=>begin('import',title,bytes),retry:dispatch});
}
export function createConnectedImporter({origin,sessionToken,onState}){return createDocxImporter({send:createFileTransport({origin,sessionToken}),onState})}

export function createDocxExporter({documentId,editor,send,onState=()=>{}}){
 uuid(documentId);for(const fn of [editor?.status,editor?.snapshot,editor?.save,editor?.retry,send,onState])requireValue(typeof fn==='function');
 let pending=null,busy=false,phase='idle';
 function status(){return {phase,busy,pending:pending!==null,canRetry:pending!==null&&!busy,canCancel:pending?.stage==='download'&&!busy}}
 function emit(){notify(onState,status())}
 function target(raw){const v=checkedView(raw);requireValue(v.document_id===documentId&&v.state==='editable'&&!v.document.is_dirty&&v.last_command?.action==='save','invalid_response');
  return {stage:'download',sha256:v.document.source_sha256,revision:v.base_storage_revision,
   request:{path:`/docx-documents/${documentId}/editor-sessions/${v.session_id}/saved-content`,body:JSON.stringify({command_id:v.last_command.command_id,expected_command_sequence:v.command_sequence,expected_session_revision:v.document.session_revision})}};
 }
 async function dispatch(retry){requireValue(!busy&&pending!==null,'busy');busy=true;emit();
  try{
   if(pending.stage==='save'){phase='saving';emit();const v=retry?await editor.retry():await editor.save();pending=target(v)}
   phase='downloading';emit();const response=await send({...pending.request});
   requireValue(response?.status===200&&response.copyKind==='saved'&&response.sha256===pending.sha256&&response.storageRevision===pending.revision
    &&response.bytes instanceof Uint8Array&&response.bytes.byteLength>0&&response.bytes.byteLength<=MAX_DOCX_BYTES,'invalid_response');
   const result={filename:documentId+'.docx',bytes:new Uint8Array(response.bytes),sha256:pending.sha256,storageRevision:pending.revision};
   pending=null;phase='ready';return result;
  }catch(_){phase='uncertain';if(pending?.stage==='save'&&editor.status().canEdit&&!editor.status().canRetry){pending=null;phase='error'}throw failure()}
  finally{busy=false;emit()}
 }
 async function exportDocx(){requireValue(!pending&&!busy,'busy');const s=editor.status();requireValue(s.canEdit&&!s.busy&&!s.canRetry,'busy');
  requireValue(editor.snapshot().document_id===documentId);pending={stage:'save'};return dispatch(false)}
 return Object.freeze({status,exportDocx,retry:()=>dispatch(true),cancel(){requireValue(!busy&&pending?.stage==='download','busy');pending=null;phase='idle';emit();return status()}});
}
