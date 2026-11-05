import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const [root,name]=process.argv.slice(2);
const {createEditorTransport,EDITOR_REQUEST_TIMEOUT_MS}=await import(pathToFileURL(root+'/src/ara/desktop/client/editor-transport.mjs'));
assert.equal(EDITOR_REQUEST_TIMEOUT_MS,30000);
const origin='http://127.0.0.1:43210',token='a'.repeat(64);
const documentId='00000000-0000-0000-0000-000000000001',sessionId='00000000-0000-0000-0000-000000000002';
const path=`/docx-documents/${documentId}/editor-sessions/${sessionId}/commands`;
const body=JSON.stringify({text:'Синтетический 🧪'}),request={path,body};
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve()};
function response({url=origin+path,status=200,text='{"ok":true}',headers={},stream,redirected=false}={}){
 const result=new Response(stream??text,{status,headers:{'Content-Type':'application/json',...headers}});
 Object.defineProperty(result,'url',{value:url});Object.defineProperty(result,'redirected',{value:redirected});
 return result;
}
function rig(options={}){
 const calls=[],timers=new Map();let serial=0,behavior=async()=>response();
 const send=createEditorTransport({origin,sessionToken:token,documentId,sessionId,
 fetchImpl:async(url,init)=>{calls.push({url,init});return behavior(url,init)},
 schedule:(fn,ms)=>{assert.equal(ms,30000);timers.set(++serial,fn);return serial},
 cancel:id=>timers.delete(id),...options});
 return{send,calls,timers,set(fn){behavior=fn},fire(){const fn=[...timers.values()][0];assert.ok(fn);fn()}};
}
const cases={
 async inert(){const r=rig();assert.equal(r.calls.length,0);assert.equal(r.timers.size,0)},
 async exact(){const r=rig();const result=await r.send(request);assert.deepEqual(result,{status:200,body:{ok:true}});assert.equal(r.calls.length,1);const{url,init}=r.calls[0];assert.equal(url,origin+path);assert.equal(init.method,'POST');assert.equal(init.body,body);const h=new Headers(init.headers);assert.equal(h.get('X-AIRA-Session'),token);assert.equal(h.get('Content-Type'),'application/json');assert.equal(init.redirect,'error');assert.equal(init.credentials,'omit');assert.equal(init.cache,'no-store');assert.equal(init.referrerPolicy,'no-referrer');assert.equal(init.mode,'same-origin');assert.equal(r.timers.size,0)},
 async origin(){for(const value of ['https://127.0.0.1:43210','http://localhost:43210','http://127.1:43210','http://127.0.0.1:80','http://127.0.0.1:65536','http://127.0.0.1:043210','http://127.0.0.1:43210/','http://127.0.0.1:43210?x','http://user@127.0.0.1:43210','http://127.0.0.1:43210#x'])assert.throws(()=>rig({origin:value}))},
 async token(){for(const value of ['',null,'A'.repeat(64),'a'.repeat(63),token+'\n'])assert.throws(()=>rig({sessionToken:value}))},
 async identity(){for(const value of [null,'../secret',documentId.toUpperCase().replace('0000','AAAA'),'not-uuid'])assert.throws(()=>rig({documentId:value}))},
 async paths(){const r=rig();for(const p of [origin+path,'//evil.invalid'+path,path+'?x',path+'#x',path+'/..',path.replace('/commands','/%63ommands'),path.replace(sessionId,documentId),path.replace('/commands','/close'),path.replace('/commands','/view')])await assert.rejects(r.send({path:p,body}));assert.equal(r.calls.length,0)},
 async input_bounds(){const r=rig();for(const b of [null,{},'x'.repeat(8*1024*1024+1),'\ud800'])await assert.rejects(r.send({path,body:b}));await assert.rejects(r.send({path:path.replace('/commands','/save'),body:'x'.repeat(65537)}));assert.equal(r.calls.length,0)},
 async status(){for(const status of [403,409,410,413,422,500,503]){const r=rig();r.set(()=>response({status,text:'{"code":"validation_error"}'}));const result=await r.send(request);assert.equal(result.status,status);assert.equal(result.body.code,'validation_error');assert.equal(r.calls.length,1)}},
 async redirects(){for(const status of [301,302,303,307,308]){const r=rig();r.set(()=>response({status,headers:{Location:'https://evil.invalid'}}));await assert.rejects(r.send(request));assert.equal(r.calls.length,1);assert.equal(r.timers.size,0)}},
 async response_url(){for(const opts of [{url:'https://evil.invalid/x'},{url:origin+path+'?x'},{redirected:true}]){const r=rig();r.set(()=>response(opts));await assert.rejects(r.send(request))}},
 async media(){for(const value of ['text/html','application/json; charset=utf-16','application/json, text/plain']){const r=rig();r.set(()=>response({headers:{'Content-Type':value}}));await assert.rejects(r.send(request))}},
 async malformed(){for(const text of ['', 'PRIVATE_NOT_JSON','{"x":NaN}',new Uint8Array([123,34,120,34,58,34,255,34,125])]){const r=rig();r.set(()=>response({text}));await assert.rejects(r.send(request),e=>!String(e).includes('PRIVATE_NOT_JSON'))}},
 async declared_length(){for(const value of ['65537','-1','bad','2']){const r=rig();r.set(()=>response({headers:{'Content-Length':value}}));await assert.rejects(r.send(request))}},
 async streamed_limit(){let cancelled=false;const r=rig();r.set(()=>response({stream:new ReadableStream({start(c){c.enqueue(new Uint8Array(65537))},cancel(){cancelled=true}})}));await assert.rejects(r.send(request));await flush();assert.equal(cancelled,true);assert.equal(r.timers.size,0)},
 async exact_limit(){const r=rig();const text='{"x":"'+'a'.repeat(65528)+'"}';assert.equal(text.length,65536);r.set(()=>response({text,headers:{'Content-Length':'65536'}}));assert.equal((await r.send(request)).body.x.length,65528)},
 async header_deadline(){const r=rig();r.set(()=>new Promise(()=>{}));const pending=r.send(request);const rejected=assert.rejects(pending);await flush();r.fire();await rejected;assert.equal(r.calls[0].init.signal.aborted,true);assert.equal(r.calls.length,1);assert.equal(r.timers.size,0)},
 async body_deadline(){let cancelled=false;const r=rig();r.set(()=>response({stream:new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('{'))},cancel(){cancelled=true}})}));const pending=r.send(request);const rejected=assert.rejects(pending);await flush();r.fire();await rejected;await flush();assert.equal(cancelled,true);assert.equal(r.calls[0].init.signal.aborted,true)},
 async busy(){const r=rig();let release;r.set(()=>new Promise(resolve=>release=resolve));const first=r.send(request);await flush();await assert.rejects(r.send(request),e=>e.code==='busy');assert.equal(r.calls.length,1);release(response());await first},
 async safe_error(){const r=rig();r.set(()=>{throw Error(token+' PRIVATE_SOURCE '+origin)});await assert.rejects(r.send(request),e=>![token,'PRIVATE_SOURCE',origin].some(v=>(String(e)+JSON.stringify(e)).includes(v)));assert.equal(r.calls.length,1);assert.equal(r.timers.size,0)},
 async cancel_error(){const r=rig({cancel:()=>{throw Error('PRIVATE_CANCEL')}});const result=await r.send(request);assert.equal(result.status,200)},
 async late_deadline(){const r=rig();let old;const send=createEditorTransport({origin,sessionToken:token,documentId,sessionId,fetchImpl:async()=>response(),schedule:fn=>{old=fn;return 1},cancel:()=>{}});assert.equal((await send(request)).status,200);old();await flush();assert.equal((await send(request)).status,200)},
 async chunks(){let cancelled=false;const r=rig();r.set(()=>response({stream:new ReadableStream({pull(c){c.enqueue(new Uint8Array(0))},cancel(){cancelled=true}})}));await assert.rejects(r.send(request));assert.equal(cancelled,true)},
 async late_fetch(){let release;const r=rig();r.set(()=>new Promise(resolve=>release=resolve));const done=assert.rejects(r.send(request));await flush();r.fire();await done;let cancelled=false;release(response({stream:new ReadableStream({cancel(){cancelled=true}})}));await flush();assert.equal(cancelled,true);assert.equal(r.calls.length,1)}
};
cases.timer_failure = async () => {
 let called=false;
 const send=createEditorTransport({origin,sessionToken:token,documentId,sessionId,
  fetchImpl:async()=>{called=true;return response()},schedule:()=>{throw Error('PRIVATE_CLOCK')},cancel:()=>{}});
 await assert.rejects(send(request),e=>!String(e).includes('PRIVATE_CLOCK'));
 assert.equal(called,false);
};
cases.hanging_cancel = async () => {
 const r=rig();let cancelled=false;
 r.set(()=>response({stream:new ReadableStream({cancel(){cancelled=true;return new Promise(()=>{})}})}));
 const pending=assert.rejects(r.send(request));await flush();r.fire();await pending;
 assert.equal(cancelled,true);
};

assert.ok(Object.hasOwn(cases,name));await cases[name]();process.stdout.write('ok '+name+'\n');
