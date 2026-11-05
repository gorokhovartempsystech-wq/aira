import {extendedReview} from './review-extensions.mjs';
import {DocxClientError, requireValue, uuid, counter, copyJson} from './protocol.mjs';
const LIMIT=16*1024*1024+65536;
const digest=v=>requireValue(typeof v==='string'&&v.length===64&&/^[0-9a-f]{64}$/.test(v),'invalid_response');
const finding=v=>requireValue(typeof v==='string'&&v.length===67&&/^df-[0-9a-f]{64}$/.test(v));
const clone=value=>copyJson(value,LIMIT);

export function createReviewSession({documentId,editor,send,makeId=()=>globalThis.crypto.randomUUID(),onState=()=>{}}){
 uuid(documentId);for(const fn of [editor?.snapshot,send,makeId,onState])requireValue(typeof fn==='function');
 const prefix=`/docx-documents/${documentId}/`;let review=null,selected=null,pending=null,busy=false,closed=false,phase='idle';
 function current(){try{const v=editor.snapshot();return review!==null&&review.matches_saved_document
   &&v.document_id===documentId&&v.document.source_sha256===review.run.source_sha256;}catch(_){return false}}
 function status(){const fresh=current();return {phase,review:review===null?null:clone(review),busy,
   canRetry:!closed&&!busy&&pending!==null,canHighlight:!closed&&phase==='ready'&&fresh,
   stale:review!==null&&!fresh};}
 function emit(){try{Promise.resolve(onState(status())).catch(()=>{});}catch(_){}}
 function alive(){requireValue(!closed,'inactive');}
 function filters(value){
   const v=copyJson(value);requireValue(v!==null&&typeof v==='object'&&!Array.isArray(v)
    &&Object.keys(v).length===3&&Array.isArray(v.disabled_types)&&v.disabled_types.length<=3
    &&new Set(v.disabled_types).size===v.disabled_types.length
    &&v.disabled_types.every(x=>['formulation','contradiction','duplicate'].includes(x))
    &&typeof v.show_questions==='boolean'&&typeof v.show_hidden==='boolean');return v;
 }
 function checked(raw,runId){
   const r=clone(raw),v=r.view,s=r.run,p=r.preferences;
   const extension=extendedReview(v);
   requireValue(r.schema_version==='docx-review-http/1'&&s.document_id===documentId
     &&(runId===null||s.run_id===runId)&&s.status==='succeeded','invalid_response');uuid(s.run_id);
   digest(s.source_sha256);counter(s.storage_revision,1n);digest(r.view_sha256);digest(r.current_sha256);counter(r.current_storage_revision,1n);
   requireValue(typeof r.matches_saved_document==='boolean'&&typeof r.fixture==='boolean'
     &&r.fixture===(s.execution_kind==='fixture')&&['fixture','local_model'].includes(s.execution_kind)
     &&r.matches_saved_document===(r.current_sha256===s.source_sha256&&r.current_storage_revision===s.storage_revision),'invalid_response');
   requireValue(p.document_id===documentId,'invalid_response');counter(p.revision);
   filters({disabled_types:p.disabled_types,show_questions:p.show_questions,show_hidden:p.show_hidden});
   requireValue((extension!==null||/^docx-review-view\/[1-5]$/.test(v.schema_version))&&v.fixture===r.fixture
     &&v.source.document_id===documentId&&v.source.source_sha256===s.source_sha256
     &&v.source.storage_revision===s.storage_revision&&Array.isArray(v.findings)
     &&Array.isArray(v.questions)&&Array.isArray(v.hidden_finding_ids)
     &&typeof v.no_findings==='boolean'&&v.no_visible_findings===(v.findings.length===0)
     &&Number.isSafeInteger(v.counts.total_findings)&&v.counts.total_findings>=v.findings.length
     &&v.counts.visible_findings===v.findings.length&&(extension!==null||v.no_findings===(v.counts.total_findings===0)),'invalid_response');
   digest(v.stored_result_sha256);for(const item of v.findings)finding(item.finding_id);
   for(const id of v.hidden_finding_ids)finding(id);
   requireValue(new Set(v.findings.map(x=>x.finding_id)).size===v.findings.length,'invalid_response');return r;
 }
 async function read(runId){
   phase='loading';emit();
   const response=await send({path:prefix+(runId===null?'analysis-review':`analysis-runs/${runId}/review`),method:'GET'});alive();
   requireValue(response?.status===200,'request_failed');const value=checked(response.body,runId);
   review=value;selected=value.run.run_id;phase='ready';emit();return status();
 }
 async function load(runId=null){
   alive();requireValue(!busy&&pending===null,'busy');if(runId!==null)uuid(runId);busy=true;
   try{return await read(runId);}catch(_){if(!closed)phase='read_error';throw new DocxClientError('request_failed');}
   finally{busy=false;emit();}
 }
 async function dispatch(){
   alive();requireValue(!busy&&pending!==null,'busy');busy=true;phase='writing';emit();const command=pending;
   try{
     const response=await send({path:command.path,method:'POST',body:command.body});alive();
     if(response?.status===409&&['preferences_conflict','idempotency_conflict'].includes(response.body?.code)){
       pending=null;phase='conflict';throw new DocxClientError('conflict');
     }
     requireValue(response?.status===200,'request_failed');const a=copyJson(response.body),r=a.receipt;
     requireValue(a.schema_version==='docx-review-http/1'&&r.document_id===documentId
       &&r.command_id===command.id&&r.expected_revision===command.revision
       &&counter(r.revision)===counter(command.revision)+1n&&r.kind===command.kind
       &&typeof r.changed==='boolean','invalid_response');
     pending=null;return await read(selected);
   }catch(error){if(!closed&&phase!=='conflict')phase=pending?'uncertain':'read_error';
     throw error instanceof DocxClientError?error:new DocxClientError('request_failed');}
   finally{busy=false;emit();}
 }
 function begin(path,kind,values){
   alive();requireValue(!busy&&pending===null&&phase==='ready'&&review!==null,'busy');
   let id;try{id=uuid(makeId());}catch(_){throw new DocxClientError('identity_unavailable');}
   const revision=review.preferences.revision;
   pending={path,id,kind,revision,body:JSON.stringify({command_id:id,expected_revision:revision,...values})};return dispatch();
 }
 return Object.freeze({status,load,retry:dispatch,
   setFilters(value){return begin(prefix+'analysis-preferences','preferences',filters(value));},
   setHidden(id,hidden){
     finding(id);requireValue(typeof hidden==='boolean');
     requireValue(review!==null&&(review.view.findings.some(x=>x.finding_id===id)||review.view.hidden_finding_ids.includes(id)));
     return begin(prefix+`analysis-runs/${selected}/findings/${id}/visibility`,hidden?'hide':'unhide',
       {result_sha256:review.view.stored_result_sha256,hidden});
   },
   clearHidden(){return begin(prefix+'analysis-preferences/clear-hidden','unhide',{});},
   dispose(){closed=true;phase='closed';emit();return status();}
 });
}
