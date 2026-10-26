"""Песочница AIRA: страница в браузере поверх движка — пока нет десктопного приложения.

    python -m aira_ml.playground --models ../models/models-0.1 [--port 8770]

Открыть http://127.0.0.1:8770. Движок работает в этом же процессе, всё локально.
Только для демо и проверки: слушает 127.0.0.1, без токена (в приложении — engine.serve с токеном).
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .engine import VERSION, Engine

SAMPLE = """# Спецификация модуля «Возвраты» / Бизнес-правила
- Возврат товара надлежащего качества возможен в течение 14 дней с даты получения.
- Товары, купленные со скидкой более 50%, можно вернуть в течение 7 дней с даты получения.
- Система должна быстро обрабатывать заявку на возврат и/или уведомлять покупателя.
# Статусная модель
- Перевод заявки в «Одобрена» возможен, только если на дату подачи заявки с даты получения прошло не более 14 дней.
# Функциональные требования
- Система должна скрывать кнопку «Вернуть», если с даты получения прошло более 14 дней.
# API returns-service
- POST /returns — ответ 422 с кодом RETURN_PERIOD_EXPIRED, если с даты получения прошло более 14 дней.
- POST /returns — поле photos (array of string), необязательное, не более 5 элементов.
# Критерии приёмки
- Дано: заказ получен 15 дней назад. Когда покупатель открывает заказ, то кнопки «Вернуть» нет.
# Тексты для клиента
- Письмо о доставке заказа: «Если товар не подошёл, вы можете вернуть его в течение 14 дней».
- FAQ: «Сколько есть времени на возврат? — Две недели с момента получения заказа».
- Push-уведомление на 11-й день после получения: «Осталось 3 дня, чтобы оформить возврат».
# Архив / Правила возврата 2023
- Возврат товара надлежащего качества возможен в течение 7 дней с даты получения.
# Заметки к релизу
- Обсуждается: продлить срок возврата до 30 дней для участников программы лояльности.
"""

PAGE = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIRA — песочница</title><style>
:root{--bg:#f7f6f2;--card:#fff;--ink:#1f1e1b;--mut:#6b6a64;--line:#e4e2da;--red:#c0392b;--redbg:#fbeaea;--yel:#9a6b00;--yelbg:#fdf3dc;--acc:#3c3489}
@media (prefers-color-scheme:dark){:root{--bg:#1c1c1a;--card:#262624;--ink:#ecebe6;--mut:#a5a39b;--line:#3a3936;--red:#f08a7e;--redbg:#3a2321;--yel:#f2c45a;--yelbg:#3a3220;--acc:#afa9ec}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:baseline}
header b{font-size:18px}header span{color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 20px}@media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
textarea{width:100%;min-height:340px;font:13px/1.5 ui-monospace,monospace;background:transparent;color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:10px}
button{font:inherit;padding:7px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.p{background:var(--acc);color:#fff;border-color:var(--acc)}button:disabled{opacity:.5}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
.frag{padding:6px 8px;border-radius:6px;cursor:pointer;font-size:13px}.frag:hover{background:var(--bg)}
.frag.sel{outline:2px solid var(--acc)}.frag small{color:var(--mut)}.st{font-size:11px;color:var(--mut);border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-left:4px}
.iss{border-left:4px solid var(--line);padding:8px 10px;margin:8px 0;border-radius:0 8px 8px 0;background:var(--bg)}
.iss.red{border-color:var(--red);background:var(--redbg)}.iss.yellow{border-color:var(--yel);background:var(--yelbg)}
.iss .t{font-size:12px;color:var(--mut)}.q{font-style:italic}.muted{color:var(--mut);font-size:13px}h3{margin:4px 0 8px;font-size:15px}
input{width:100%;font:inherit;padding:7px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--ink)}
</style></head><body>
<header><b>AIRA</b><span>песочница · движок __ENGINE__ · модели __MODELS__ · всё локально, без интернета</span></header>
<main>
<section class="card"><h3>Документ</h3>
<textarea id="doc"></textarea>
<div class="row"><button class="p" id="rev">Ревью</button><button id="parse">Разобрать на пункты</button><span class="muted" id="st"></span></div>
<h3>Пункты <span class="muted">— выберите пункт, чтобы проверить влияние правки</span></h3><div id="frags" class="muted">Нажмите «Разобрать на пункты».</div>
<div id="edit" style="display:none"><div class="row"><input id="newtext"></div>
<div class="row"><button class="p" id="imp">Проверить влияние правки</button></div></div>
</section>
<section class="card"><h3 id="rtitle">Результат</h3><div id="out" class="muted">Здесь появятся замечания.</div></section>
</main>
<script>
const $=id=>document.getElementById(id);$('doc').value=__SAMPLE__;
let frags=[],sel=null;const T={formulation:'формулировка',duplicate:'дубль',contradiction:'противоречие',affected:'затронуто правкой'};
const S={active:'',exception:'исключение',deprecated:'архив',delta:'черновик',discussion:'обсуждение'};
async function call(p,b){$('st').textContent='считаю…';const t=performance.now();const r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});const j=await r.json();$('st').textContent=`${((performance.now()-t)/1000).toFixed(2)} с`;return j}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function renderFrags(){$('frags').innerHTML=frags.map(f=>`<div class="frag ${sel&&sel.id==f.id?'sel':''}" data-id="${f.id}"><small>${f.id}</small> ${esc(f.text)}${S[f.status]?`<span class="st">${S[f.status]}</span>`:''}</div>`).join('');
 document.querySelectorAll('.frag').forEach(d=>d.onclick=()=>{sel=frags.find(f=>f.id==d.dataset.id);$('edit').style.display='';$('newtext').value=sel.text;$('newtext').focus();renderFrags()})}
function issue(x){const rel=x.related?`<div class="t">↔ ${x.related.fragment_id}${S[x.related.status]?' ('+S[x.related.status]+')':''}: ${esc(x.related.quote)}</div>`:'';
 const sug=x.suggestion?`<div class="t">исправить: «${esc(x.suggestion.before)}» → «${esc(x.suggestion.after)}»</div>`:'';
 return `<div class="iss ${x.light}"><div class="t">${T[x.type]||x.type} · ${x.light=='red'?'уверенно':'проверьте'} · ${x.confidence} · ${x.fragment_id}</div><div>${esc(x.span.quote)}</div>${rel}<div class="t">${esc(x.explanation)}</div>${sug}</div>`}
$('parse').onclick=async()=>{const j=await call('/api/parse',{text:$('doc').value});frags=j.fragments;sel=null;$('edit').style.display='none';renderFrags()};
$('rev').onclick=async()=>{const j=await call('/api/review',{text:$('doc').value});$('rtitle').textContent=`Ревью: ${j.issues.length} замечаний`;
 const q=j.questions.length?`<h3>Что уточнить</h3>${j.questions.map(x=>`<div class="q">• ${esc(x)}</div>`).join('')}`:'';
 $('out').innerHTML=(j.issues.map(issue).join('')||'<div class="muted">Замечаний нет.</div>')+q+`<p class="muted">проверено пунктов: ${j.checked.active}, пропущено (архив, черновики, обсуждения): ${j.checked.skipped_status}</p>`};
$('imp').onclick=async()=>{if(!frags.length)await $('parse').onclick();const j=await call('/api/impact',{fragments:frags,fragment_id:sel.id,new:$('newtext').value});
 $('rtitle').textContent=`Влияние правки ${j.source}: ${j.issues.length} мест`;
 $('out').innerHTML=`<p class="muted">искали по: ${j.search_terms.map(esc).join(', ')} · кандидатов: ${j.checked.candidates}</p>`+(j.issues.map(issue).join('')||'<div class="muted">Других мест, которые нужно обновить, не найдено.</div>')};
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    eng = Engine(a.models, a.threads)
    page = (PAGE.replace("__ENGINE__", VERSION)
            .replace("__MODELS__", eng.manifest["version"]).replace("__SAMPLE__", json.dumps(SAMPLE, ensure_ascii=False)))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def _send(self, code, body, ctype):
            b = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(200, page, "text/html; charset=utf-8")
            self._send(404, "не найдено", "text/plain; charset=utf-8")

        def do_POST(self):
            try:
                d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                frags = d.get("fragments") or eng.parse_text(d.get("text", ""), "Документ")
                if self.path == "/api/parse":
                    res = {"fragments": frags}
                elif self.path == "/api/review":
                    res = eng.review(frags, d.get("disabled_types", []), d.get("dismissed", []))
                elif self.path == "/api/impact":
                    res = eng.impact(frags, d["new"], d.get("fragment_id"), d.get("old"))
                else:
                    return self._send(404, "{}", "application/json")
                self._send(200, json.dumps(res, ensure_ascii=False), "application/json; charset=utf-8")
            except (KeyError, ValueError) as e:
                self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False), "application/json; charset=utf-8")

    print(f"AIRA песочница: http://127.0.0.1:{a.port}  (модели {eng.manifest['version']}, загрузка {eng.load_s} с)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
