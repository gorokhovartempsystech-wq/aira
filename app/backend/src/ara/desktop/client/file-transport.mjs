import {DocxClientError, requireValue, uuid, counter} from './protocol.mjs';
export const DOCX_MIME='application/vnd.openxmlformats-officedocument.wordprocessingml.document';
export const MAX_DOCX_BYTES=33554432;
export const FILE_REQUEST_TIMEOUT_MS=30000;
const JSON_LIMIT=65536;
export function checkedTitle(value){
 requireValue(typeof value==='string'&&value.length<=400&&[...value].length>=1&&[...value].length<=200&&value.trim().length>0&&!value.includes('\0'));
 for(const char of value){const n=char.codePointAt(0);requireValue(n<0xd800||n>0xdfff)}return value;
}
function cancelStream(stream){try{Promise.resolve(stream?.cancel()).catch(()=>{})}catch(_){}}
const valid=ok=>requireValue(ok,'invalid_response');
export function createFileTransport({origin,sessionToken,fetchImpl=(...args)=>globalThis.fetch(...args),schedule=(fn,ms)=>setTimeout(fn,ms),cancel=id=>clearTimeout(id)}){
 const match=typeof origin==='string'&&/^http:\/\/127\.0\.0\.1:([1-9][0-9]{3,4})$/.exec(origin);
 requireValue(match&&match[0]===origin&&Number(match[1])>=1024&&Number(match[1])<=65535);
 requireValue(typeof sessionToken==='string'&&sessionToken.length===64&&/^[0-9a-f]{64}$/.test(sessionToken));
 for(const fn of [fetchImpl,schedule,cancel])requireValue(typeof fn==='function');let active=false;
 return Object.freeze(async function send(request){
  requireValue(!active,'busy');let path,body,kind;
  try{
   requireValue(request&&[Object.prototype,null].includes(Object.getPrototypeOf(request))&&Object.keys(request).every(k=>['path','body'].includes(k)));
   path=request.path;body=request.body;requireValue(typeof path==='string'&&path.length<=2600);
   const upload=/^\/docx-documents\/([^/]+)\/(create|import)\?title=(.*)$/.exec(path);
   const saved=/^\/docx-documents\/([^/]+)\/editor-sessions\/([^/]+)\/saved-content$/.exec(path);
   if(upload){uuid(upload[1]);kind=upload[2];const title=checkedTitle(decodeURIComponent(upload[3]));requireValue(encodeURIComponent(title)===upload[3]);
    if(kind==='create')requireValue(body===undefined);
    else{requireValue(body instanceof Uint8Array&&body.byteLength>0&&body.byteLength<=MAX_DOCX_BYTES);body=new Uint8Array(body)}
   }else{requireValue(saved!==null&&saved[0]===path);uuid(saved[1]);uuid(saved[2]);kind='saved';requireValue(typeof body==='string'&&body.length<=JSON_LIMIT&&new TextEncoder().encode(body).length<=JSON_LIMIT)}
  }catch(_){throw new DocxClientError('invalid_input')}
  active=true;let controller,reader,timer,scheduled=false,done=false,complete=false;
  try{
   controller=new AbortController();let expire;const deadline=new Promise((_,reject)=>{expire=reject});
   timer=schedule(()=>{if(!done){controller.abort();expire(new DocxClientError('transport_error'))}},FILE_REQUEST_TIMEOUT_MS);scheduled=true;
   async function receive(){
    const headers={'X-AIRA-Session':sessionToken,Accept:kind==='saved'?DOCX_MIME:'application/json'};
    if(kind!=='create')headers['Content-Type']=kind==='import'?'application/octet-stream':'application/json';
    const response=await fetchImpl(origin+path,{method:'POST',body,headers,redirect:'error',credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer',mode:'same-origin',signal:controller.signal});
    if(done||controller.signal.aborted){cancelStream(response?.body);throw new DocxClientError('transport_error')}
    try{
     valid(Number.isInteger(response.status)&&response.status>=200&&response.status<=599&&(response.status<300||response.status>=400));
     valid(response.url===origin+path&&response.redirected===false&&['basic','default'].includes(response.type));
     const binary=kind==='saved'&&response.status===200,maximum=binary?MAX_DOCX_BYTES:JSON_LIMIT;
     const media=response.headers.get('Content-Type');valid(binary?media===DOCX_MIME:typeof media==='string'&&/^application\/json(?:;\s*charset=utf-8)?$/i.test(media));
     valid([null,'identity'].includes(response.headers.get('Content-Encoding')));
     const length=response.headers.get('Content-Length');valid(length===null||(/^(0|[1-9][0-9]{0,7})$/.test(length)&&Number(length)<=maximum));
     reader=response.body.getReader();const chunks=[];let size=0,count=0;
     for(;;){const part=await reader.read();if(done||controller.signal.aborted)throw new DocxClientError('transport_error');if(part.done)break;
      valid(++count<=8192&&part.value instanceof Uint8Array&&size+part.value.byteLength<=maximum);chunks.push(new Uint8Array(part.value));size+=part.value.byteLength;}
     valid(length===null||Number(length)===size);const bytes=new Uint8Array(size);let offset=0;for(const part of chunks){bytes.set(part,offset);offset+=part.length}
     if(!binary)return {status:response.status,body:JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes))};
     valid(size>0);const etag=response.headers.get('ETag');valid(typeof etag==='string'&&/^"[0-9a-f]{64}"$/.test(etag));
     const storageRevision=response.headers.get('X-ARA-Storage-Revision');counter(storageRevision,1n);
     valid(response.headers.get('X-ARA-Copy-Kind')==='saved');
     const digest=new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256',bytes));
     const sha256=Array.from(digest,x=>x.toString(16).padStart(2,'0')).join('');valid(etag==='"'+sha256+'"');
     return {status:response.status,bytes,sha256,storageRevision,copyKind:'saved'};
    }catch(error){if(!reader)cancelStream(response.body);throw error instanceof DocxClientError&&error.code==='transport_error'?error:new DocxClientError('invalid_response')}
   }
   const result=await Promise.race([receive(),deadline]);complete=true;return result;
  }catch(error){throw error instanceof DocxClientError?error:new DocxClientError('transport_error')}
  finally{done=true;if(!complete)controller?.abort();if(reader){if(!complete)cancelStream(reader);try{reader.releaseLock()}catch(_){}}if(scheduled){try{cancel(timer)}catch(_){}}active=false}
 });
}
