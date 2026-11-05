import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
let input='';for await(const chunk of process.stdin)input+=chunk;
const job=JSON.parse(input);input='';
const module=name=>import(pathToFileURL(job.root+'/src/ara/desktop/client/'+name+'.mjs'));
const {createDocxSession}=await module('docx-session');
const {createEditorTransport}=await module('editor-transport');
const {createAnalysisTransport}=await module('analysis-transport');
const {createAnalysisSession}=await module('analysis-session');
const {createReviewTransport}=await module('review-transport');
const {createReviewSession}=await module('review-session');
const options={origin:job.origin,sessionToken:job.token,documentId:job.view.document_id};
const editor=createDocxSession({view:job.view,send:createEditorTransport({...options,sessionId:job.view.session_id})});
editor.start();await editor.edit({action:'insert_text',value:'Проверка клиента 🧪 '});
let lose=true;const posts=[],transport=createAnalysisTransport(options);
const analysis=createAnalysisSession({documentId:job.view.document_id,editor,send:async request=>{
 const response=await transport(request);
 if(request.method==='POST'&&!request.path.endsWith('/stop'))posts.push({...request});
 if(lose&&request.path.endsWith('/analysis-runs')){lose=false;throw Error('synthetic lost acceptance')}
 return response;
}});
async function finished(){const end=Date.now()+90000;while(analysis.status().phase!=='finished'){
 assert.ok(Date.now()<end,'fixture analysis did not finish');
 assert.notEqual(analysis.status().phase,'poll_error');await new Promise(resolve=>setTimeout(resolve,20));
}return analysis.status().receipt;}
try{
 await assert.rejects(analysis.check());await analysis.retryAdmission();assert.deepEqual(posts[0],posts[1]);
 const first=await finished();assert.equal(first.state.status,'succeeded');assert.equal(first.fixture,true);
 const saved=editor.snapshot();assert.equal(first.state.source_sha256,saved.base_sha256);
 assert.equal(first.state.storage_revision,saved.base_storage_revision);

 const review=createReviewSession({documentId:job.view.document_id,editor,send:createReviewTransport(options)});
 try{
  await review.load(first.run_id);assert.equal(review.status().canHighlight,true);
  assert.equal(review.status().review.fixture,true);
  const finding=review.status().review.view.findings[0];
  await review.setHidden(finding.finding_id,true);
  assert.equal(review.status().review.view.no_visible_findings,true);
  assert.equal(review.status().review.view.no_findings,false);
  await review.setFilters({disabled_types:[],show_questions:true,show_hidden:true});
  assert.ok(review.status().review.view.findings.some(x=>x.finding_id===finding.finding_id));
  await review.setHidden(finding.finding_id,false);
  await review.setHidden(finding.finding_id,true);
  await review.clearHidden();assert.equal(review.status().review.view.hidden_finding_ids.length,0);
  await review.setFilters({disabled_types:[finding.type],show_questions:false,show_hidden:false});
  assert.equal(review.status().review.view.no_visible_findings,true);
  assert.equal(review.status().review.view.questions.length,0);
  await review.setFilters({disabled_types:[],show_questions:true,show_hidden:false});
  await editor.edit({action:'insert_text',value:'Новая правка '});
  assert.equal(review.status().canHighlight,false);assert.equal(review.status().stale,true);
  await editor.edit({action:'undo'});assert.equal(review.status().canHighlight,true);
  process.stdout.write(JSON.stringify({first,saved}));
 }finally{review.dispose();}

}finally{analysis.dispose();editor.stop();}
