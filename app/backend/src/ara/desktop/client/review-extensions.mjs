import {requireValue} from './protocol.mjs';
const checks=new Set(['formulation','duplicate','contradiction']);
const valid=x=>requireValue(x,'invalid_response');
export function extendedReview(v){
 if(v.schema_version!=='docx-review-view/6-draft-1')return null;
 const c=v.analysis_coverage;
 valid(c&&['complete','partial'].includes(c.state));
 for(const key of ['planned_checks','completed_checks']){
  valid(Array.isArray(c[key])&&c[key].every(x=>checks.has(x))&&new Set(c[key]).size===c[key].length);
 }
 valid(c.planned_checks.length>0&&c.completed_checks.every(x=>c.planned_checks.includes(x)));
 valid(['top_k','exhaustive','none'].includes(c.pair_selection));
 const total=c.pair_candidates_total,done=c.pair_candidates_completed;
 valid((total===null&&done===null)||(Number.isSafeInteger(total)&&Number.isSafeInteger(done)&&0<=done&&done<=total&&total<=100000000));
 if(c.pair_selection==='none')valid((total===null||total===0)&&(done===null||done===0));
 if(c.state==='complete')valid(c.reason===null&&c.planned_checks.length===c.completed_checks.length&&total===done);
 else valid(['deadline','resource_limit'].includes(c.reason));
 valid(Array.isArray(v.standalone_questions));
 const ids=new Set();
 for(const q of v.standalone_questions){
  valid(typeof q.question_id==='string'&&/^sq-[0-9a-f]{64}$/.test(q.question_id)&&!ids.has(q.question_id));ids.add(q.question_id);
  valid(typeof q.text==='string'&&q.text.length>0&&typeof q.reason==='string'&&q.reason.length>0);
  valid(Array.isArray(q.evidence)&&q.evidence.length>0&&q.evidence.length<=16);
  for(const e of q.evidence){
   valid(typeof e.fragment_id==='string'&&Number.isSafeInteger(e.start)&&Number.isSafeInteger(e.end)&&e.start>=0&&e.end>e.start);
   valid(typeof e.quote==='string'&&Array.from(e.quote).length===e.end-e.start&&Array.isArray(e.slices)&&e.slices.length>0);
  }
 }
 valid(Number.isSafeInteger(v.counts.visible_questions)&&v.counts.visible_questions===v.questions.length+v.standalone_questions.length);
 valid(Number.isSafeInteger(v.counts.total_questions)&&v.counts.total_questions>=v.counts.visible_questions);
 valid(v.no_findings===(v.counts.total_findings===0&&c.state==='complete'&&v.counts.total_questions===0));
 return {partial:c.state==='partial',coverage:c};
}
