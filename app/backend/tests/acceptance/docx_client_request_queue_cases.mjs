import assert from 'node:assert/strict';import {pathToFileURL} from 'node:url';
const root=process.argv[2],name=process.argv[3];
const {createRequestQueue}=await import(pathToFileURL(root+'/src/ara/desktop/client/request-queue.mjs'));
const queue=createRequestQueue(),calls=[];let release;
const first=queue.wrap(async r=>{calls.push(r);await new Promise(resolve=>{release=resolve});if(name==='failure')throw Error('synthetic failure');return r.body});
const next=queue.wrap(async r=>{calls.push(r);return r.body});assert.equal(calls.length,0);
const a=first({body:'first'});await Promise.resolve();assert.equal(calls.length,1);
if(name==='bound'){
 const jobs=[];for(let i=0;i<127;i++)jobs.push(next({body:String(i)}));assert.throws(()=>next({body:'overflow'}),e=>e.code==='busy');release();await a;await Promise.all(jobs);assert.equal(calls.length,128);assert.equal(await next({body:'after'}),'after');
}else{
 const r={body:'second'},b=next(r);r.body='mutated';await Promise.resolve();assert.equal(calls.length,1);release();
 if(name==='failure')await assert.rejects(a,/synthetic failure/);else assert.equal(await a,'first');
 assert.equal(await b,'second');assert.deepEqual(calls.map(x=>x.body),['first','second']);
}
console.log('ok '+name);
