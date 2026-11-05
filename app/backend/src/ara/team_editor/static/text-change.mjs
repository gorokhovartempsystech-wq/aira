export function textChange(before,after){
 if(before===after)return null;
 const a=Array.from(before),b=Array.from(after);let start=0,end=a.length,tail=b.length;
 while(start<end&&start<tail&&a[start]===b[start])start++;
 while(end>start&&tail>start&&a[end-1]===b[tail-1]){end--;tail--;}
 return {start,end,before:a.slice(start,end).join(''),after:b.slice(start,tail).join('')};
}

export function rangeCommand(paragraph,blocks,text){
 const c=textChange(paragraph.text,text);if(!c)return null;
 const position=offset=>{
  const span=paragraph.edit_spans.find(s=>s.kind==='text'&&s.start<=offset&&offset<s.end)||paragraph.edit_spans.find(s=>s.kind==='text'&&s.end===offset);
  if(!span)throw new Error('В этом месте нет поддерживаемого текстового диапазона.');
  return {anchor:{...paragraph.anchor,path:span.path},offset:offset-span.start};
 };
 const ix=blocks.findIndex(x=>JSON.stringify(x.anchor.path)===JSON.stringify(paragraph.anchor.path));
 const point={block_index:ix>=0?ix:blocks.findIndex(x=>x.kind==='paragraph'),offset:ix>=0?c.start+Array.from(c.after).length:0,affinity:'left'};
 return {action:'range_edit',after:{anchor:point,focus:point},value:[{start:position(c.start),end:position(c.end),expected_text:c.before,replacement_text:c.after}]};
}
