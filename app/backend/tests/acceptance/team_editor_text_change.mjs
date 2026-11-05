import assert from 'node:assert/strict';
import {textChange,rangeCommand} from '../../src/ara/team_editor/static/text-change.mjs';
for(const [before,after] of [['abc','abc'],['abc','abXc'],['abc','ac'],['🧪 срок 5','🧪 срок 10'],['','новое'],['текст','']]){
 const c=textChange(before,after);
 if(before===after){assert.equal(c,null);continue;}
 const a=Array.from(before);
 assert.equal(a.slice(0,c.start).join('')+c.after+a.slice(c.end).join(''),after);
 assert.equal(a.slice(c.start,c.end).join(''),c.before);
}
console.log('Unicode edits passed');

const anchor={source_sha256:'a'.repeat(64),part_name:'word/document.xml',path:[0,1]};
const p={kind:'paragraph',anchor,text:'🧪 срок 5 дней',edit_spans:[{kind:'text',path:[0,1,0,0],start:0,end:7},{kind:'text',path:[0,1,1,0],start:7,end:13}]};
const c=rangeCommand(p,[p],'🧪 срок 10 дней');
assert.equal(c.value[0].start.offset,0);
assert.deepEqual(c.value[0].start.anchor.path,[0,1,1,0]);
assert.equal(c.value[0].expected_text,'5');
assert.equal(c.value[0].replacement_text,'10');
assert.equal(c.after.focus.offset,9);
assert.equal(rangeCommand(p,[p],p.text),null);
console.log('Exact span range command passed');
