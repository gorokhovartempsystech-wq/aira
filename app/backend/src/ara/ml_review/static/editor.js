"use strict";
const el=id=>document.getElementById(id);
const key="aira-team-editor-v1";
let state={id:null,revision:null,imported:false,title:"Новый документ",text:"",savedText:null,lastReview:null};
let busy=false, job=null;
try { const old=JSON.parse(localStorage.getItem(key)); if(old && typeof old.text==="string") state={...state,...old}; } catch(_) {}
el("title").value=state.title;el("text").value=state.text;
function persist(){state.title=el("title").value;state.text=el("text").value;try{localStorage.setItem(key,JSON.stringify(state));}catch(_){el("document-status").textContent="Не удалось сохранить черновик в браузере. Сохраните DOCX.";}}
function controls(){for(const id of ["new","save","download","import","check"])el(id).disabled=busy;
el("text").readOnly=busy||state.imported;el("title").disabled=busy||Boolean(state.revision);el("save").disabled=busy||state.imported;el("stop").hidden=!job;el("import-note").hidden=!state.imported;}
function message(text){el("status").textContent=text;}
async function request(path,options={}){const r=await fetch(path,{...options,cache:"no-store"});if(!r.ok)throw new Error(r.status===409?"Документ изменился или другая проверка ещё идёт. Обновите документ.":`Операция не выполнена (${r.status}).`);return r.json();}
async function save(){if(state.imported)return;if(!el("text").value.trim())throw new Error("Введите текст требований.");
if(state.revision&&state.savedText===el("text").value)return;
state.id=state.id||crypto.randomUUID();persist();
const saved=await request("/editor/documents",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({document_id:state.id,expected_revision:state.revision,title:state.title,text:state.text})});
state.revision=saved.storage_revision;state.savedText=state.text;persist();el("document-status").textContent=`DOCX сохранён · версия ${state.revision}`;}
async function action(fn){if(busy)return;busy=true;controls();try{await fn();}catch(e){message(e.message);}finally{busy=false;controls();}}
el("text").addEventListener("input",()=>{persist();if(state.lastReview)message("Текст изменён. Замечания относятся к предыдущей проверке; запустите её заново.");});el("title").addEventListener("input",persist);
el("save").onclick=()=>action(save);
el("new").onclick=()=>{if(busy)return;if(state.text&&state.savedText!==state.text&&!confirm("Несохранённый черновик будет заменён. Создать новый документ?"))return;state={id:null,revision:null,imported:false,title:"Новый документ",text:"",savedText:null,lastReview:null};el("title").value=state.title;el("text").value="";el("findings").replaceChildren();persist();controls();message("Проверка ещё не запускалась.");};
el("download").onclick=()=>action(async()=>{await save();if(!state.id)throw new Error("Нет сохранённого документа.");const a=document.createElement("a");a.href=`/docx-documents/${state.id}/content`;a.download=state.title+".docx";a.click();});
el("import").onchange=()=>action(async()=>{const file=el("import").files[0];if(!file)return;if(file.size>33554432)throw new Error("Максимальный размер — 32 МБ.");
if(state.text&&state.savedText!==state.text&&!confirm("Заменить текущий несохранённый черновик импортированным документом?"))return;
const id=crypto.randomUUID();const saved=await request(`/docx-documents/${id}/import?title=${encodeURIComponent(file.name.slice(0,200))}`,{method:"POST",headers:{"Content-Type":"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},body:file});
const view=await request(`/docx-documents/${id}/view`);const lines=[];function collect(blocks){for(const b of blocks||[]){if(b.kind==="paragraph")lines.push(b.text);else if(b.kind==="table")for(const row of b.rows)for(const cell of row.cells)collect(cell.blocks);}}
collect(view.blocks);state={id,revision:saved.storage_revision,imported:true,title:file.name,text:lines.join("\n"),savedText:lines.join("\n"),lastReview:null};el("title").value=state.title;el("text").value=state.text;persist();el("findings").replaceChildren();el("document-status").textContent="Импортированный DOCX сохранён без изменений. Просмотр упрощённый.";message("Документ готов к проверке. Поддержка сложной структуры ограничена.");});
function render(payload,outdated=false){el("findings").replaceChildren();const r=payload.result;
message((outdated?"Результат устарел. ":"")+(payload.incomplete?"Проверка неполная: "+payload.partial_reason:r.no_findings?"В выполненных проверках замечаний не найдено.":`Найдено замечаний: ${r.findings.length}.`));
for(const f of r.findings){const card=document.createElement("article");card.className="review-card";const h=document.createElement("h4");h.textContent={formulation:"Формулировка",duplicate:"Возможный дубль",contradiction:"Возможное противоречие"}[f.type]||f.type;card.append(h);
for(const q of [f.primary.quote,f.related?.quote]){if(!q)continue;const b=document.createElement("blockquote");b.textContent=q;b.onclick=()=>{const pos=el("text").value.indexOf(q);if(pos>=0){el("text").focus();el("text").setSelectionRange(pos,pos+q.length);}};card.append(b);}
for(const t of [f.explanation,f.question])if(t){const p=document.createElement("p");p.textContent=t;card.append(p);}el("findings").append(card);}
const note=document.createElement("p");note.textContent=payload.coverage_note;el("findings").append(note);}
el("check").onclick=()=>action(async()=>{await save();message("Запускаем локальную модель…");const started=await request(`/docx-documents/${state.id}/model-reviews`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_revision:String(state.revision)})});job=started.id;controls();try{let result;
do{result=await request(`/docx-documents/${state.id}/model-reviews/${job}`);if(result.status==="running"){message("Проверка идёт · лимит 5 минут");await new Promise(r=>setTimeout(r,600));}}while(result.status==="running");
if(result.status==="succeeded"){state.lastReview=job;persist();render(result.result,result.outdated);}else if(result.status==="cancelled")message("Проверка остановлена.");else message(({unsupported_document:"Структура или стили этого DOCX пока не поддерживаются для полной проверки. Текст не проверен.",empty_document:"Нет текста для проверки.",timeout:"Истекли 5 минут. Проверка остановлена."})[result.error]||"Ошибка локального анализа. Повторите проверку.");}finally{job=null;controls();}});
el("stop").onclick=async()=>{if(!job)return;try{await request(`/docx-documents/${state.id}/model-reviews/${job}`,{method:"DELETE"});}catch(e){message(e.message);}};
controls();
if(state.lastReview&&state.id)request(`/docx-documents/${state.id}/model-reviews/${state.lastReview}`).then(r=>{if(r.status==="succeeded")render(r.result,r.outdated||state.text!==state.savedText);}).catch(()=>message("Предыдущий результат не удалось загрузить."));
