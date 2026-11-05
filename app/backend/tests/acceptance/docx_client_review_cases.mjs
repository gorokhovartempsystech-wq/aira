import assert from 'node:assert/strict';import {pathToFileURL} from 'node:url';
const root=process.argv[2],name=process.argv[3];
const {createReviewSession}=await import(pathToFileURL(root+'/src/ara/desktop/client/review-session.mjs'));
const uid=n=>'00000000-0000-0000-0000-'+String(n).padStart(12,'0');const doc=uid(1),run=uid(2),digest='a'.repeat(64),fid='df-'+'b'.repeat(64);
let ram=digest,revision=0,hidden=false,filtered=false,lose=false,conflict=false,failRead=false,hold=null,id=10;
const calls=[];
function result(){const findings=hidden||filtered?[]:[{finding_id:fid,type:'formulation',primary:{quote:'Synthetic'},question:null}];return {schema_version:'docx-review-http/1',run:{document_id:doc,run_id:run,status:'succeeded',source_sha256:digest,storage_revision:'1',execution_kind:'fixture'},preferences:{document_id:doc,revision:String(revision),disabled_types:filtered?['formulation']:[],show_questions:true,show_hidden:false},view:{schema_version:'docx-review-view/5',source:{document_id:doc,source_sha256:digest,storage_revision:'1'},stored_result_sha256:'c'.repeat(64),findings,questions:[],hidden_finding_ids:hidden?[fid]:[],counts:{total_findings:1,visible_findings:findings.length},no_findings:false,no_visible_findings:findings.length===0,fixture:true},view_sha256:'d'.repeat(64),current_storage_revision:'1',current_sha256:digest,matches_saved_document:true,fixture:true}}
const receipts=new Map();
async function send(req){calls.push({...req});if(hold)return hold(req);if(req.method==='GET'){if(failRead)throw Error('synthetic');return {status:200,body:result()}}if(conflict)return {status:409,body:{code:'preferences_conflict'}};
 const b=JSON.parse(req.body);let ack=receipts.get(b.command_id);if(!ack){revision++;if('hidden' in b)hidden=b.hidden;if('disabled_types' in b)filtered=b.disabled_types.length>0;if(req.path.endsWith('clear-hidden'))hidden=false;ack={schema_version:'docx-review-http/1',receipt:{document_id:doc,command_id:b.command_id,expected_revision:b.expected_revision,revision:String(revision),kind:'hidden' in b?(b.hidden?'hide':'unhide'):req.path.endsWith('clear-hidden')?'unhide':'preferences',changed:true}};receipts.set(b.command_id,ack)}
 if(lose){lose=false;throw Error('lost ack')}return {status:200,body:ack};}
const editor={snapshot:()=>({document_id:doc,document:{source_sha256:ram}})};
const client=createReviewSession({documentId:doc,editor,send,makeId:()=>uid(id++)});
assert.equal(calls.length,0);
if(name==='dispose'){let release;hold=()=>new Promise(r=>release=r);const p=client.load(run);client.dispose();release({status:200,body:result()});await assert.rejects(p);assert.equal(client.status().phase,'closed');assert.equal(client.status().review,null);}
else if(name==='transport_deadline'){
 const {createReviewTransport}=await import(pathToFileURL(root+'/src/ara/desktop/client/review-transport.mjs'));
 let expire;const t=createReviewTransport({origin:'http://127.0.0.1:19876',sessionToken:'a'.repeat(64),documentId:doc,
 fetchImpl:()=>new Promise(()=>{}),schedule:(fn,ms)=>{assert.equal(ms,30000);expire=fn;return 1},cancel:()=>{}});
 const pending=t({path:'/docx-documents/'+doc+'/analysis-review',method:'GET'});expire();await assert.rejects(pending,e=>e.code==='transport_error');
}else if(name==='transport'){
 const {createReviewTransport}=await import(pathToFileURL(root+'/src/ara/desktop/client/review-transport.mjs'));
 let hits=0;const origin='http://127.0.0.1:19876';const t=createReviewTransport({origin,sessionToken:'a'.repeat(64),documentId:doc,fetchImpl:async(url,o)=>{hits++;assert.equal(o.redirect,'error');return {status:200,url,redirected:false,type:'basic',headers:new Headers({'Content-Type':'application/json'}),body:new Response('{}').body}}});
 await assert.rejects(t({path:'/docx-documents/'+uid(9)+'/analysis-review',method:'GET'}));await assert.rejects(t({path:'/docx-documents/'+doc+'/analysis-runs',method:'POST',body:'{}'}));assert.equal(hits,0);await t({path:'/docx-documents/'+doc+'/analysis-runs/'+run+'/review',method:'GET'});assert.equal(hits,1);
}else{
 await client.load(run);assert.equal(client.status().canHighlight,true);
 if(name==='load'){assert.equal(client.status().review.fixture,true);const value=client.status();value.review.view.findings.length=0;assert.equal(client.status().review.view.findings.length,1);}
 else if(name==='clean'){hold=async()=>{const r=result();r.view.findings=[];r.view.no_findings=true;r.view.no_visible_findings=true;r.view.counts={total_findings:0,visible_findings:0};return {status:200,body:r}};await client.load(run);assert.equal(client.status().review.view.no_findings,true);}
 else if(name==='invalid_hash'){hold=async()=>{const r=result();r.view.stored_result_sha256+='\n';return {status:200,body:r}};await assert.rejects(client.load(run));assert.equal(client.status().canHighlight,false);}
 else if(name==='late_command'){let release;hold=()=>new Promise(r=>release=r);const p=client.clearHidden();client.dispose();release({status:200,body:{}});await assert.rejects(p);assert.equal(calls.length,2);assert.equal(client.status().phase,'closed');}
 else if(name==='stale'){ram='b'.repeat(64);assert.equal(client.status().canHighlight,false);assert.equal(client.status().stale,true);ram=digest;assert.equal(client.status().canHighlight,true);}
 else if(name==='foreign'){hold=async()=>({status:200,body:{...result(),run:{...result().run,document_id:uid(99)}}});await assert.rejects(client.load(run));assert.equal(client.status().canHighlight,false);}
 else if(name==='empty'){await client.setFilters({disabled_types:['formulation'],show_questions:true,show_hidden:false});assert.equal(client.status().review.view.no_findings,false);assert.equal(client.status().review.view.no_visible_findings,true);}
 else if(name==='retry'){lose=true;await assert.rejects(client.setHidden(fid,true));const original=calls.at(-1);await client.retry();assert.deepEqual(calls.at(-2),original);assert.equal(revision,1);assert.equal(client.status().review.view.no_visible_findings,true);}
 else if(name==='conflict'){conflict=true;await assert.rejects(client.clearHidden());assert.equal(client.status().phase,'conflict');assert.equal(client.status().canRetry,false);conflict=false;await client.load(run);assert.equal(client.status().phase,'ready');}
 else if(name==='refresh_failure'){failRead=true;await assert.rejects(client.clearHidden());assert.equal(client.status().canRetry,false);assert.equal(revision,1);failRead=false;await client.load(run);assert.equal(revision,1);}
 else throw Error(name);
}
client.dispose();console.log('ok '+name);
