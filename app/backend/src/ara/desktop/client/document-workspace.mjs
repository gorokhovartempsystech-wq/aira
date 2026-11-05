import {DocxClientError, requireValue, uuid, counter, copyJson, checkedView, checkedAck} from './protocol.mjs';
import {createWorkspaceTransport} from './workspace-transport.mjs';
import {createEditorTransport} from './editor-transport.mjs';
import {createDocxSession} from './docx-session.mjs';
import {createAnalysisTransport} from './analysis-transport.mjs';
import {createAnalysisSession} from './analysis-session.mjs';
import {createReviewTransport} from './review-transport.mjs';
import {createReviewSession} from './review-session.mjs';
import {createFileTransport} from './file-transport.mjs';
import {createDocxExporter} from './docx-files.mjs';
import {createRequestQueue} from './request-queue.mjs';
const prefix=id=>`/docx-documents/${id}/`;
const digest=x=>requireValue(typeof x==='string'&&x.length===64&&/^[0-9a-f]{64}$/.test(x));
const fail=()=>new DocxClientError('request_failed');

export function createDocumentWorkspace({send,createClient,makeId=()=>globalThis.crypto.randomUUID(),onState=()=>{}}){
 for(const fn of [send,createClient,makeId,onState])requireValue(typeof fn==='function');
 const tabs=new Map();let active=null,opening=false;
 function tab(id){uuid(id);const t=tabs.get(id);requireValue(t!==undefined);return t;}
 function status(){return {activeDocumentId:active,opening,tabs:[...tabs.values()].map(t=>({documentId:t.id,phase:t.phase,
  dirty:t.clients?t.clients.editor.status().dirty??t.view.document.is_dirty:t.view?.document.is_dirty??null,
  canRecover:t.phase==='recovery_required',canRetryOpen:t.phase==='open_uncertain',canRetryClose:t.phase==='close_uncertain'}))};}
 function emit(){try{Promise.resolve(onState(status())).catch(()=>{});}catch(_){}}
 function recovery(raw,id){const r=copyJson(raw);requireValue(r.kind==='recovery'&&r.document?.document_id===id);
  uuid(r.registry_id);counter(r.open_sequence);counter(r.checkpoint_revision);digest(r.document.current_sha256);
  requireValue(['absent','empty','working','pending'].includes(r.phase));if(['working','pending'].includes(r.phase))digest(r.working_sha256);return r;}
 async function readRecovery(id){const r=await send({path:prefix(id)+'editor-recovery',method:'GET'});requireValue(r?.status===200,'request_failed');return recovery(r.body,id);}
 function install(t,v){t.view=checkedView(v);requireValue(t.view.document_id===t.id,'invalid_response');
  if(t.view.state!=='editable'){t.phase=t.view.state;return;}
  const clients=createClient(copyJson(t.view));requireValue(clients?.editor&&clients?.analysis&&clients?.review);
  t.clients=clients;clients.editor.start();t.phase='open';active=t.id;
 }
 async function submitOpen(t){
  try{const r=await send(t.openRequest);requireValue(r?.status===200,'request_failed');const b=copyJson(r.body);
   requireValue(b.kind==='opened'&&b.accepted_open_sequence===t.recovery.open_sequence
    &&counter(b.next_open_sequence)>counter(b.accepted_open_sequence)
    &&b.view?.registry_id===t.recovery.registry_id,'invalid_response');install(t,b.view);t.openRequest=null;return status();
  }catch(_){t.phase='open_uncertain';throw fail();}finally{emit();}
 }
 async function open(id,{recover=false}={}){
  uuid(id);requireValue(typeof recover==='boolean');let t=tabs.get(id);
  if(t?.phase==='open'){active=id;emit();return status();}
  requireValue(!opening&&(!t||t.phase==='recovery_required'||t.phase==='read_error'),'busy');opening=true;
  if(!t){t={id,phase:'opening',clients:null,view:null};tabs.set(id,t);}emit();
  try{t.recovery=await readRecovery(id);
   const needs=['working','pending'].includes(t.recovery.phase);
   if(needs&&!recover){t.phase='recovery_required';return status();}
   const body={registry_id:t.recovery.registry_id,client_open_id:uuid(makeId()),expected_open_sequence:t.recovery.open_sequence,
    expected_checkpoint_revision:t.recovery.checkpoint_revision,mode:needs?'recover':'current'};
   t.openRequest={path:prefix(id)+'editor-sessions',method:'POST',body:JSON.stringify(body)};
   return await submitOpen(t);
  }catch(_){if(!t.openRequest)t.phase='read_error';throw fail();}finally{opening=false;emit();}
 }
 async function retryOpen(id){const t=tab(id);requireValue(!opening&&t.phase==='open_uncertain'&&t.openRequest,'busy');opening=true;
  try{return await submitOpen(t);}finally{opening=false;emit();}}
 async function reconcile(id){const t=tab(id);requireValue(['recovery_pending','reconcile_uncertain'].includes(t.phase)&&!t.busy,'busy');t.busy=true;
  try{if(!t.reconcileRequest){const v=t.view;t.reconcileId=uuid(makeId());t.reconcileRequest={path:prefix(id)+`editor-sessions/${v.session_id}/reconcile`,method:'POST',body:JSON.stringify({command_id:t.reconcileId,expected_command_sequence:v.command_sequence,expected_session_revision:v.document.session_revision})};}
   const r=await send(t.reconcileRequest);requireValue(r?.status===200,'request_failed');
   const v=checkedAck(r.body,{before:t.view,id:t.reconcileId,operation:'save',action:'save'});
   install(t,v);t.reconcileRequest=null;return status();
  }catch(_){t.phase='reconcile_uncertain';throw fail();}finally{t.busy=false;emit();}
 }
 function finishClose(t){tabs.delete(t.id);if(active===t.id)active=tabs.keys().next().value??null;t.phase='closed';emit();return status();}
 async function submitClose(t){
  try{const r=await send(t.closeRequest);
   if(r?.status===410){const proof=await readRecovery(t.id);
    requireValue(proof.document.current_sha256===t.view.document.source_sha256||(
     ['working','pending'].includes(proof.phase)&&proof.working_sha256===t.view.document.source_sha256
     &&counter(proof.checkpoint_revision)>=counter(t.view.checkpoint_revision)),'invalid_response');
   }else{requireValue(r?.status===200,'request_failed');const b=copyJson(r.body);
    requireValue(b.kind==='closed'&&b.document_id===t.id&&b.registry_id===t.view.registry_id
     &&b.session_id===t.view.session_id&&b.mode==='checkpoint'
     &&counter(b.checkpoint_revision)>counter(t.view.checkpoint_revision),'invalid_response');}
   return finishClose(t);
  }catch(_){t.phase='close_uncertain';throw fail();}finally{emit();}
 }
 async function close(id){const t=tab(id);
  if(['recovery_required','read_error'].includes(t.phase)&&!t.openRequest&&!t.clients)return finishClose(t);
  requireValue(t.phase==='open'&&!t.busy,'busy');
  const e=t.clients.editor.status(),a=t.clients.analysis.status(),r=t.clients.review.status(),f=t.clients.files?.status();
  requireValue(!f?.busy&&!f?.pending,'busy');
  requireValue(!e.busy&&!e.canRetry&&e.canEdit&&!a.busy&&!a.canStop&&!a.canRetryAdmission&&!a.canRetrySave&&!r.busy&&!r.canRetry,'busy');
  t.phase='checkpointing';t.busy=true;emit();
  try{
   try{t.view=checkedView(await t.clients.editor.checkpoint());}catch(_){t.phase='open';throw fail();}
   const body={command_id:uuid(makeId()),expected_command_sequence:t.view.command_sequence,expected_session_revision:t.view.document.session_revision};
   t.closeRequest={path:prefix(id)+`editor-sessions/${t.view.session_id}/close`,method:'POST',body:JSON.stringify(body)};
   t.clients.editor.stop();t.clients.analysis.dispose();t.clients.review.dispose();t.phase='closing';
   return await submitClose(t);
  }catch(error){if(t.phase==='checkpointing')t.phase='open';throw error;}
  finally{t.busy=false;emit();}
 }
 async function retryClose(id){const t=tab(id);requireValue(t.phase==='close_uncertain'&&!t.busy,'busy');t.busy=true;
  try{return await submitClose(t);}finally{t.busy=false;emit();}}
 function client(id){const t=tab(id);requireValue(t.clients!==null);const out={};
  for(const [name,api]of Object.entries(t.clients)){out[name]={};for(const [key,fn]of Object.entries(api)){
   if(typeof fn!=='function'||key==='dispose'||(name==='editor'&&['start','stop'].includes(key)))continue;out[name][key]=(...args)=>{
    if(!['status','snapshot'].includes(key))requireValue(t.phase==='open','busy');
    if(name!=='files'&&!(name==='analysis'&&key==='stop')&&!['status','snapshot'].includes(key)){const f=t.clients.files?.status();requireValue(!f?.busy&&!f?.pending,'busy');}
    if(name==='files'&&key==='exportDocx'){const a=t.clients.analysis.status();requireValue(!a.busy&&!a.canRetrySave&&!a.canRetryAdmission,'busy');}
    if(name==='editor'&&!['status','snapshot'].includes(key))requireValue(!['saving','admitting','admission_uncertain'].includes(t.clients.analysis.status().phase),'busy');
    return fn(...args);
   };}Object.freeze(out[name]);}return Object.freeze(out);
 }
 return Object.freeze({status,open:async(...args)=>{await open(...args);return status();},
  retryOpen:async(...args)=>{await retryOpen(...args);return status();},reconcile,close,retryClose,client,
  focus(id){const t=tab(id);requireValue(t.phase==='open');active=id;emit();return status();},
  metadata(id){const t=tab(id);return copyJson(t.clients?t.clients.editor.snapshot():t.view);},
  async closeAll(){for(const id of [...tabs.keys()])await close(id);return status();}
 });
}

export function createConnectedWorkspace({origin,sessionToken,onState}){
 const queue=createRequestQueue();
 const send=queue.wrap(createWorkspaceTransport({origin,sessionToken}));
 let workspace;
 const update=()=>onState?.(workspace.status());
 workspace=createDocumentWorkspace({send,onState,createClient:view=>{
  const options={origin,sessionToken,documentId:view.document_id};
  const editor=createDocxSession({view,send:queue.wrap(createEditorTransport({...options,sessionId:view.session_id})),onState:update});
  const analysisTransport=createAnalysisTransport(options),analysisQueued=queue.wrap(analysisTransport);
  const analysisSend=request=>request.method==='POST'&&request.path.endsWith('/stop')?analysisTransport(request):analysisQueued(request);
  return {editor,analysis:createAnalysisSession({documentId:view.document_id,editor,send:analysisSend,onState:update}),
   review:createReviewSession({documentId:view.document_id,editor,send:queue.wrap(createReviewTransport(options)),onState:update}),
   files:createDocxExporter({documentId:view.document_id,editor,send:queue.wrap(createFileTransport({origin,sessionToken})),onState:update})};
 }});
 return workspace;
}
