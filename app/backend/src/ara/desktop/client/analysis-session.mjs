import {DocxClientError, requireValue, uuid, counter, copyJson} from './protocol.mjs';

const TERMINAL = new Set(['succeeded','failed','cancelled','timed_out']);
const hash = value => requireValue(typeof value === 'string' && /^[0-9a-f]{64}$/.test(value));
const safeError = () => new DocxClientError('request_failed');

// One document's analysis lane. The injected editor remains the sole command owner.
export function createAnalysisSession({documentId, editor, send,
  makeId=()=>globalThis.crypto.randomUUID(), schedule=(fn,ms)=>setTimeout(fn,ms),
  cancel=id=>clearTimeout(id), onState=()=>{}}) {
  uuid(documentId);
  for(const fn of [editor?.save,editor?.retry,editor?.status,send,makeId,schedule,cancel,onState])
    requireValue(typeof fn==='function');
  const prefix=`/docx-documents/${documentId}/`;
  let phase='idle', pending=null, receipt=null, binding=null, timer=null;
  let closed=false, ordinary=false, stopping=false, stopRequested=false;
  let generation=0;
  const finished=()=>receipt?.phase==='finished' && TERMINAL.has(receipt?.state?.status);
  const rejected=()=>receipt?.phase==='not_admitted'&&receipt.run_id===null&&receipt.state===null;
  const settled=()=>finished()||rejected();
  function status(){return copyJson({phase,receipt,stopRequested,
    busy:ordinary,canCheck:!closed&&!ordinary&&(!pending||settled()),
    canStop:!closed&&pending!==null&&!settled()&&!stopping,
    canRetryAdmission:!closed&&!ordinary&&!rejected()&&pending!==null&&['admission_uncertain','not_admitted','poll_error'].includes(phase),
    canRetrySave:!closed&&!ordinary&&phase==='save_uncertain'});}
  function emit(){try{Promise.resolve(onState(status())).catch(()=>{});}catch(_){}}
  function clearTimer(){const old=timer;timer=null;if(old!==null)try{cancel(old.handle);}catch(_){}}
  function live(g){requireValue(!closed&&g===generation,'inactive');}
  function arm(){
    clearTimer();if(closed||!pending||finished()||phase==='not_admitted')return;
    const token={handle:null};timer=token;
    try{token.handle=schedule(()=>{if(timer!==token)return;timer=null;void refresh().catch(()=>{});},250);}
    catch(_){timer=null;phase='poll_error';emit();}
  }
  function accept(raw){
    const value=copyJson(raw);
    requireValue(value.schema_version==='docx-analysis-http/1'&&value.document_id===documentId
      &&value.client_request_id===pending.key&&typeof value.fixture==='boolean'
      &&typeof value.stop_requested==='boolean'
      &&['admitting','queued','active','settling','finished','not_admitted'].includes(value.phase),'invalid_response');
    if(value.run_id!==null)uuid(value.run_id);
    if(value.state!==null){
      const s=value.state;
      requireValue(s.document_id===documentId&&s.client_request_id===pending.key
        &&s.run_id===value.run_id&&s.source_sha256===binding.digest
        &&s.storage_revision===binding.revision
        &&['queued','running','cancel_requested',...TERMINAL].includes(s.status)
        &&['fixture','local_model'].includes(s.execution_kind)
        &&value.fixture===(s.execution_kind==='fixture'),'invalid_response');
      requireValue((value.phase==='finished')===TERMINAL.has(s.status),'invalid_response');
    }else requireValue(value.phase!=='finished','invalid_response');
    if(receipt?.run_id!==null&&receipt?.run_id!==undefined&&value.run_id!==null)
      requireValue(value.run_id===receipt.run_id,'invalid_response');
    // An older in-flight poll cannot regress a terminal result or proven refusal.
    if(settled())return;
    stopRequested ||= value.stop_requested;
    receipt=value;
    phase=finished()?'finished':value.phase==='not_admitted'?'not_admitted':'waiting';
    if(finished()||phase==='not_admitted')clearTimer();
    emit();
  }
  function identity(){let key;try{key=uuid(makeId());}catch(_){throw new DocxClientError('identity_unavailable');}
    requireValue(key!==pending?.key,'identity_unavailable');return key;}
  function saved(view){
    const v=copyJson(view);
    requireValue(v.document_id===documentId&&v.document?.is_dirty===false
      &&v.last_command?.action==='save'&&v.document.source_sha256===v.base_sha256,'invalid_response');
    uuid(v.registry_id);uuid(v.session_id);uuid(v.last_command.command_id);
    counter(v.command_sequence,1n);counter(v.document.session_revision);counter(v.base_storage_revision,1n);hash(v.base_sha256);
    binding={digest:v.base_sha256,revision:v.base_storage_revision};
    const key=identity();
    const body=JSON.stringify({client_request_id:key,registry_id:v.registry_id,session_id:v.session_id,
      save_command_id:v.last_command.command_id,command_sequence:v.command_sequence,
      session_revision:v.document.session_revision,storage_revision:v.base_storage_revision,source_sha256:v.base_sha256});
    pending={key,path:prefix+'analysis-runs',body};receipt=null;stopRequested=false;
  }
  async function submit(g){
    phase='admitting';emit();
    try{
      const result=await send({path:pending.path,method:'POST',body:pending.body});live(g);
      requireValue(result?.status===202,'request_failed');accept(result.body);arm();return status();
    }catch(error){if(!closed&&g===generation){phase='admission_uncertain';emit();}throw safeError();}
  }
  async function saveAndCheck(retry){
    requireValue(!closed&&!ordinary,'busy');
    requireValue(retry?phase==='save_uncertain':status().canCheck,'busy');
    clearTimer();ordinary=true;const g=++generation;phase='saving';emit();
    let view;
    try{
      try{view=await (retry?editor.retry():editor.save());live(g);}
      catch(error){if(!closed){phase=editor.status().canRetry?'save_uncertain':'save_error';emit();}throw safeError();}
      saved(view);return await submit(g);
    }finally{ordinary=false;emit();}
  }
  async function refresh(){
    requireValue(!closed&&pending!==null&&!ordinary,'busy');
    if(settled())return status();
    clearTimer();ordinary=true;const g=generation;
    try{
      const result=await send({path:prefix+'analysis-requests/'+pending.key,method:'GET'});live(g);
      requireValue(result?.status===200,'request_failed');accept(result.body);arm();return status();
    }catch(error){if(!closed&&!settled()){phase='poll_error';clearTimer();emit();}throw safeError();}
    finally{ordinary=false;emit();}
  }
  return Object.freeze({status,check:()=>saveAndCheck(false),retrySave:()=>saveAndCheck(true),refresh,
    async retryAdmission(){
      requireValue(status().canRetryAdmission,'busy');ordinary=true;
      try{return await submit(generation);}finally{ordinary=false;emit();}
    },
    async retryAnalysis(){
      requireValue(!closed&&!ordinary&&finished(),'busy');
      const run=receipt.run_id,key=identity();ordinary=true;generation++;clearTimer();
      pending={key,path:prefix+'analysis-runs/'+run+'/retry',body:JSON.stringify({client_request_id:key})};
      receipt=null;stopRequested=false;
      try{return await submit(generation);}finally{ordinary=false;emit();}
    },
    async stop(){
      requireValue(status().canStop,'busy');stopping=true;stopRequested=true;const g=generation;emit();
      try{
        const result=await send({path:prefix+'analysis-requests/'+pending.key+'/stop',method:'POST',body:'{}'});live(g);
        requireValue(result?.status===202,'request_failed');accept(result.body);if(!ordinary)arm();return status();
      }catch(_){throw safeError();}finally{stopping=false;emit();}
    },
    dispose(){closed=true;generation++;clearTimer();phase='closed';emit();return status();}
  });
}
