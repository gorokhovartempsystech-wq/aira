"""Прототип приложения AIRA по пути пользователя от 27.10 (шаги 04–11): один документ, локальный анализ,
проверка по кнопке. Работает на настоящем движке и моделях; окно — браузер на 127.0.0.1.

    python -m aira_ml.proto --models dist/models-0.2 [--port 8780] [--data ~/.aira-proto]

Что есть: вкладки документов, новый / последний / учебный пример / импорт Word; редактор с заголовками
и списками, автосохранение и черновик в браузере на случай сбоя; проверка по кнопке с ходом анализа,
остановкой, лимитом 5 минут и отметкой частичной проверки; замечания с привязкой к тексту, фильтры,
вопросы (можно выключить); после правки — устаревшие замечания и «что ещё задела правка»; экспорт
.docx / .md и копирование. Шаги 01–03 (скачать, установить, лицензия) — вне прототипа.

Данные — JSON в папке --data, ничего не уходит в сеть. Слушает только 127.0.0.1 и отклоняет чужие
Host/Origin (защита от DNS-rebinding). Прототип без токена — для демо; в приложении — engine.serve с токеном.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import io
import json
import re
import secrets
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from .engine import VERSION, Cancelled, Engine

LIMIT_S = 300                                   # «Ограничение времени выполнения (5 минут)»
MAX_VERSIONS = 30
STAGES = {"parse": "Разбираю документ на пункты", "formulation": "Проверяю формулировки",
          "duplicate": "Ищу повторы и похожие пункты", "logic": "Проверяю логику: противоречия",
          "questions": "Собираю вопросы", "impact": "Ищу, что ещё задела правка"}

SAMPLE_TITLE = "Учебный пример: модуль «Возвраты»"
SAMPLE = """# Спецификация модуля «Возвраты» / Бизнес-правила
- Возврат товара надлежащего качества возможен в течение 14 дней с даты получения.
- Товары, купленные со скидкой более 50%, можно вернуть в течение 7 дней с даты получения.
- Система должна быстро обрабатывать заявку на возврат и/или уведомлять покупателя.
# Статусная модель
- Перевод заявки в «Одобрена» возможен, только если на дату подачи заявки с даты получения прошло не более 14 дней.
# Функциональные требования
- Система должна скрывать кнопку «Вернуть», если с даты получения прошло более 14 дней.
- Возврат товаров, купленных со скидкой более 50%, не допускается.
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


# --- хранилище ---------------------------------------------------------------------------

class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser()
        (self.root / "docs").mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _p(self, doc_id):
        if not re.fullmatch(r"d[0-9a-f]{12}", doc_id or ""):
            raise KeyError("нет такого документа")
        return self.root / "docs" / f"{doc_id}.json"

    def get(self, doc_id):
        p = self._p(doc_id)
        if not p.exists():
            raise KeyError("нет такого документа")
        return json.loads(p.read_text(encoding="utf-8"))

    def put(self, doc):
        with self.lock:
            tmp = self._p(doc["id"]).with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._p(doc["id"]))          # атомарно: сбой не портит сохранённый документ

    def create(self, title, text="", sample=False):
        now = time.time()
        doc = {"id": "d" + secrets.token_hex(6), "title": title or "Без названия", "text": text, "sample": sample,
               "created": now, "updated": now, "versions": [], "check": None}
        self.put(doc)
        return doc

    def list(self):
        out = []
        for p in (self.root / "docs").glob("d*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            out.append({"id": d["id"], "title": d["title"], "updated": d["updated"], "sample": d.get("sample", False),
                        "checked": bool(d.get("check"))})
        return sorted(out, key=lambda d: -d["updated"])

    def session(self, data=None):
        p = self.root / "session.json"
        if data is not None:
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"open": [], "active": None}


def add_version(doc, text, reason):
    if doc["versions"] and doc["versions"][-1]["text"] == text:
        return
    doc["versions"].append({"ts": time.time(), "text": text, "reason": reason})
    doc["versions"] = doc["versions"][-MAX_VERSIONS:]


# --- проверка ---------------------------------------------------------------------------------

class Job:
    def __init__(self, doc_id):
        self.id = secrets.token_hex(6)
        self.doc_id, self.state, self.stage, self.pct = doc_id, "running", "parse", 0.0
        self.started, self.cancel, self.result, self.error = time.time(), False, None, None

    def view(self):
        return {"id": self.id, "state": self.state, "stage": self.stage, "stage_ru": STAGES.get(self.stage, ""),
                "pct": round(self.pct, 3), "elapsed": round(time.time() - self.started, 1), "limit": LIMIT_S,
                "error": self.error, "result": self.result if self.state == "done" else None}


def changed_fragments(prev, cur):
    """Пары (было, стало) для пунктов, которые изменились с прошлой проверки (удалённые и новые не считаем)."""
    prev_texts = {f["text"] for f in prev}
    cur_texts = {f["text"] for f in cur}
    gone = [f for f in prev if f["text"] not in cur_texts]
    out = []
    for f in cur:
        if f["text"] in prev_texts or not gone:
            continue
        best = max(gone, key=lambda g: difflib.SequenceMatcher(None, g["text"], f["text"]).ratio())
        if difflib.SequenceMatcher(None, best["text"], f["text"]).ratio() >= 0.55:
            out.append((best, f))
            gone.remove(best)
    return out


def run_check(eng, lock, store, job, text, opts):
    try:
        def prog(stage, pct):
            if job.cancel:
                raise Cancelled()
            job.stage, job.pct = stage, pct

        doc = store.get(job.doc_id)
        prev = doc.get("check")
        add_version(doc, text, "перед проверкой")            # «Сохранение проверяемой версии»
        doc["text"], doc["updated"] = text, time.time()
        store.put(doc)
        prog("parse", 0.01)
        frags = Engine.parse_text(text, doc["title"] or "Документ")
        disabled = [t for t in opts.get("disabled", []) if t in ("formulation", "duplicate", "contradiction")]
        with lock:                                            # одна проверка за раз: CPU не делим
            res = eng.review(frags, disabled, (), prog, deadline=job.started + LIMIT_S)
            impact, changes = [], []
            if prev and prev.get("text") != text and "affected" not in opts.get("disabled", []):
                prog("impact", 0.98)
                changes = changed_fragments(prev.get("frags", []), frags)[:5]
                changed_ids = {n["id"] for _, n in changes}
                best = {}
                for old, new in changes:
                    probe = [dict(f, text=old["text"]) if f["id"] == new["id"] else f for f in frags]
                    for iss in eng.impact(probe, new["text"], new["id"])["issues"]:
                        if iss["fragment_id"] in changed_ids:   # этот пункт уже поправили в той же правке
                            continue
                        iss["change"] = {"fragment_id": new["id"], "old": old["text"], "new": new["text"]}
                        k = iss["fragment_id"]
                        if k not in best or iss["confidence"] > best[k]["confidence"]:
                            best[k] = iss
                impact = sorted(best.values(), key=lambda x: (x["light"] != "red", -x["confidence"]))
        by = {f["id"]: f for f in frags}
        for iss in res["issues"] + impact:                    # смещения в тексте документа — для подсветки
            f = by.get(iss["fragment_id"])
            iss["offset"] = f["offset"] + iss["span"]["start"] if f else None
            if not opts.get("questions", True):
                iss["question"] = None
        result = {"ts": time.time(), "text": text, "engine": res["engine"], "models": res["models"],
                  "issues": res["issues"], "impact": impact,
                  "changes": [{"old": o["text"], "new": n["text"]} for o, n in changes],
                  "questions": res["questions"] if opts.get("questions", True) else [],
                  "checked": res["checked"], "partial": res["partial"], "seconds": round(time.time() - job.started, 1),
                  "frags": [{"id": f["id"], "text": f["text"], "offset": f["offset"]} for f in frags]}
        doc = store.get(job.doc_id)
        doc["check"] = result
        store.put(doc)
        job.result, job.state, job.pct = result, "done", 1.0
    except Cancelled:
        job.state = "cancelled"
    except Exception as e:                                    # показываем ошибку и даём перезапустить
        job.state, job.error = "error", f"{type(e).__name__}: {e}"


# --- импорт и экспорт Word ----------------------------------------------------------------------

def import_docx(data):
    from .realdocs import docx_blocks
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(data)
        name = f.name
    try:
        return "\n".join(docx_blocks(name))
    finally:
        Path(name).unlink(missing_ok=True)


def export_docx(title, text):
    """Минимальный .docx без сторонних библиотек: заголовки, пункты списка, абзацы."""
    def run(t, bold=False, size=None):
        rpr = ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/>' if size else "")
        return f'<w:r>{"<w:rPr>" + rpr + "</w:rPr>" if rpr else ""}<w:t xml:space="preserve">{escape(t)}</w:t></w:r>'

    paras = [f"<w:p>{run(title, True, 32)}</w:p>"]
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            paras.append(f"<w:p>{run(s.lstrip('# '), True, 28)}</w:p>")
        elif re.match(r"^([-*+]|\d+[.)])\s+", s):
            paras.append(f'<w:p><w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr>{run("• " + re.sub(r"^([-*+]|\d+[.)])\s+", "", s))}</w:p>')
        else:
            paras.append(f"<w:p>{run(s)}</w:p>")
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + "".join(paras) + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


# --- HTTP ----------------------------------------------------------------------------------------

def make_handler(eng, store, port):
    jobs, lock = {}, threading.Lock()
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{h}" for h in hosts}
    page = (PAGE.replace("__ENGINE__", VERSION).replace("__MODELS__", eng.manifest["version"])
            .replace("__STAGES__", json.dumps(STAGES, ensure_ascii=False)))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(b)

        def _guard(self):
            if self.headers.get("Host") not in hosts:
                self._send(403, {"error": "доступ только с 127.0.0.1"})
                return False
            o = self.headers.get("Origin")
            if self.command != "GET" and o and o not in origins:
                self._send(403, {"error": "чужой Origin"})
                return False
            return True

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 20_000_000:
                raise ValueError("слишком большой запрос")
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            if not self._guard():
                return
            path, _, query = self.path.partition("?")
            try:
                if path in ("/", "/index.html"):
                    return self._send(200, page, "text/html; charset=utf-8")
                if path == "/api/state":
                    return self._send(200, {"docs": store.list(), "session": store.session(),
                                            "engine": VERSION, "models": eng.manifest["version"]})
                m = re.fullmatch(r"/api/docs/(\w+)", path)
                if m:
                    return self._send(200, store.get(m[1]))
                m = re.fullmatch(r"/api/jobs/(\w+)", path)
                if m:
                    j = jobs.get(m[1])
                    return self._send(200, j.view()) if j else self._send(404, {"error": "нет такой проверки"})
                m = re.fullmatch(r"/api/export/(\w+)", path)
                if m:
                    d = store.get(m[1])
                    fmt = "md" if "fmt=md" in query else "docx"
                    safe = re.sub(r"[^\w\- .«»]+", "_", d["title"]).strip() or "document"
                    disp = {"Content-Disposition": f"attachment; filename=\"aira.{fmt}\"; filename*=UTF-8''"
                            + quote(f"{safe}.{fmt}")}
                    if fmt == "md":
                        return self._send(200, f"# {d['title']}\n\n{d['text']}", "text/markdown; charset=utf-8", disp)
                    return self._send(200, export_docx(d["title"], d["text"]),
                                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document", disp)
                self._send(404, {"error": "не найдено"})
            except KeyError as e:
                self._send(404, {"error": str(e).strip("'")})

        def do_POST(self):
            if not self._guard():
                return
            try:
                d = self._body()
                if self.path == "/api/docs":
                    if d.get("sample"):
                        return self._send(200, store.create(SAMPLE_TITLE, SAMPLE, sample=True))
                    return self._send(200, store.create(d.get("title", "Новый документ"), d.get("text", "")))
                if self.path == "/api/import":
                    text = import_docx(base64.b64decode(d["data"]))
                    if not text.strip():
                        return self._send(400, {"error": "в файле не нашлось текста"})
                    title = re.sub(r"\.docx$", "", d.get("name", "Импорт"), flags=re.I)
                    return self._send(200, store.create(title, text))
                if self.path == "/api/session":
                    return self._send(200, store.session({"open": d.get("open", []), "active": d.get("active")}))
                if self.path == "/api/check":
                    doc_id = d["id"]
                    store.get(doc_id)
                    if any(j.doc_id == doc_id and j.state == "running" for j in jobs.values()):
                        return self._send(409, {"error": "проверка этого документа уже идёт"})
                    text = d.get("text", "")
                    if not Engine.parse_text(text):
                        return self._send(400, {"error": "Нечего проверять: добавьте требования. Заголовки и строки короче 12 символов не проверяются."})
                    j = Job(doc_id)
                    jobs[j.id] = j
                    threading.Thread(target=run_check, args=(eng, lock, store, j, text, d.get("opts", {})), daemon=True).start()
                    return self._send(200, j.view())
                m = re.fullmatch(r"/api/jobs/(\w+)/cancel", self.path)
                if m and m[1] in jobs:
                    jobs[m[1]].cancel = True
                    return self._send(200, jobs[m[1]].view())
                self._send(404, {"error": "не найдено"})
            except KeyError as e:
                self._send(404, {"error": f"не найдено: {e}"})
            except (ValueError, zipfile.BadZipFile) as e:
                self._send(400, {"error": f"неверный запрос: {e}"})

        def do_PUT(self):
            if not self._guard():
                return
            try:
                m = re.fullmatch(r"/api/docs/(\w+)", self.path)
                if not m:
                    return self._send(404, {"error": "не найдено"})
                d, doc = self._body(), store.get(m[1])
                if "title" in d:
                    doc["title"] = (d["title"] or "Без названия")[:200]
                if "text" in d and d["text"] != doc["text"]:
                    if d.get("version"):
                        add_version(doc, doc["text"], d["version"])
                    doc["text"] = d["text"]
                doc["updated"] = time.time()
                store.put(doc)
                self._send(200, {"id": doc["id"], "updated": doc["updated"]})
            except KeyError as e:
                self._send(404, {"error": str(e).strip("'")})
            except ValueError as e:
                self._send(400, {"error": f"неверный запрос: {e}"})

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--data", default="~/.aira-proto")
    a = ap.parse_args()
    eng = Engine(a.models, a.threads)
    store = Store(a.data)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(eng, store, a.port))
    print(f"AIRA прототип: http://127.0.0.1:{a.port}  (модели {eng.manifest['version']}, загрузка {eng.load_s} с, "
          f"данные {store.root})", flush=True)
    srv.serve_forever()


PAGE = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIRA</title><style>
:root{--bg:#f6f5f1;--card:#fff;--ink:#1f1e1b;--mut:#6b6a64;--line:#e3e1d9;--soft:#efede6;--acc:#3c3489;--acc2:#ebe9f8;
--red:#b3261e;--redbg:#fcebea;--yel:#8a5a00;--yelbg:#fdf3dc;--ok:#2e6b3a;--okbg:#e6f2e8;--grey:#9a988f}
@media (prefers-color-scheme:dark){:root{--bg:#1b1b19;--card:#252523;--ink:#ecebe6;--mut:#a5a39b;--line:#3a3936;--soft:#2e2e2b;
--acc:#afa9ec;--acc2:#2f2d45;--red:#f08a7e;--redbg:#3a2321;--yel:#f2c45a;--yelbg:#3a3220;--ok:#8fd19e;--okbg:#1f3324;--grey:#77756e}}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--ink);display:flex;flex-direction:column}
button{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer}
button:hover{background:var(--soft)}button.p{background:var(--acc);border-color:var(--acc);color:#fff}button.p:hover{filter:brightness(1.08)}
button:disabled{opacity:.5;cursor:default}button.g{border-color:transparent;background:transparent}
header{display:flex;align-items:center;gap:10px;padding:8px 14px;border-bottom:1px solid var(--line);background:var(--card)}
header .logo{font-weight:700;letter-spacing:.5px}header .meta{margin-left:auto;color:var(--mut);font-size:12px;white-space:nowrap}
#tabs{display:flex;gap:4px;overflow-x:auto;flex:1;min-width:0}
.tab{display:flex;align-items:center;gap:6px;padding:5px 10px;border-radius:8px;cursor:pointer;white-space:nowrap;max-width:240px;color:var(--mut)}
.tab.on{background:var(--acc2);color:var(--ink)}.tab span{overflow:hidden;text-overflow:ellipsis}.tab .x{opacity:.5;padding:0 2px}.tab .x:hover{opacity:1}
main{flex:1;min-height:0;display:flex}
#home{flex:1;overflow:auto;padding:32px 16px}#home .wrap{max-width:760px;margin:0 auto}
.big{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:18px 0 28px}
.big button{padding:16px;text-align:left;border-radius:12px}.big b{display:block;margin-bottom:2px}.big small{color:var(--mut)}
.recent div{display:flex;justify-content:space-between;padding:8px 10px;border-radius:8px;cursor:pointer}.recent div:hover{background:var(--soft)}
.badge{font-size:11px;padding:1px 6px;border-radius:5px;background:var(--soft);color:var(--mut);margin-left:6px}
#ed{flex:1;display:none;min-height:0}#ed.on{display:flex}
.left{flex:1.25;display:flex;flex-direction:column;min-width:0;border-right:1px solid var(--line)}
.right{flex:1;display:flex;flex-direction:column;min-width:320px;max-width:560px;background:var(--card)}
.bar{display:flex;gap:6px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
#title{flex:1;min-width:160px;font:600 16px system-ui,sans-serif;border:0;background:transparent;color:var(--ink);padding:4px 2px}
#title:focus{outline:2px solid var(--acc2);border-radius:6px}
#txt{flex:1;resize:none;border:0;padding:16px 18px;font:14px/1.65 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--bg);color:var(--ink);outline:none}
#txt::selection{background:#ffd76a;color:#000}
.foot{display:flex;justify-content:space-between;padding:5px 12px;font-size:12px;color:var(--mut);border-top:1px solid var(--line)}
.notice{margin:8px 12px 0;padding:8px 10px;border-radius:8px;background:var(--yelbg);color:var(--ink);font-size:13px;display:flex;gap:8px;align-items:center}
.notice.info{background:var(--acc2)}
.panel{flex:1;overflow:auto;padding:12px}
.checkbox{padding:12px;border-bottom:1px solid var(--line)}
.prog{height:6px;background:var(--soft);border-radius:4px;overflow:hidden;margin:10px 0 6px}.prog i{display:block;height:100%;background:var(--acc);width:0;transition:width .3s}
.opts{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:10px;font-size:13px;color:var(--mut)}
.chip{border-radius:999px;padding:2px 10px;font-size:12px}.chip.off{opacity:.45;text-decoration:line-through}
.sec{margin:14px 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut)}
.iss{border:1px solid var(--line);border-left:4px solid var(--grey);border-radius:8px;padding:9px 11px;margin:8px 0;cursor:pointer;background:var(--card)}
.iss:hover{border-color:var(--acc)}.iss.red{border-left-color:var(--red)}.iss.yellow{border-left-color:var(--yel)}
.iss .h{font-size:12px;color:var(--mut);display:flex;gap:8px;flex-wrap:wrap}.iss .h b{color:var(--ink)}
.iss .q{margin:4px 0;font-size:13px}.iss .ex{font-size:13px;color:var(--mut)}.iss .rel{font-size:12px;color:var(--mut);margin-top:4px;border-top:1px dashed var(--line);padding-top:4px}
.iss .fix{font-size:12px;margin-top:4px}.iss .ask{font-size:13px;font-style:italic;margin-top:4px}
.iss.old{opacity:.55;border-left-color:var(--grey)}.iss.old .q{text-decoration:line-through}
.empty{padding:28px 12px;text-align:center;color:var(--mut)}.empty b{display:block;font-size:16px;color:var(--ok);margin-bottom:4px}
.pill{font-size:11px;padding:1px 7px;border-radius:999px;background:var(--soft)}.pill.r{background:var(--redbg);color:var(--red)}.pill.y{background:var(--yelbg);color:var(--yel)}
.err{background:var(--redbg);color:var(--ink);padding:9px 10px;border-radius:8px;margin-top:8px;font-size:13px}
.menu{position:relative}.menu .dd{display:none;position:absolute;right:0;top:110%;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:4px;z-index:5;min-width:180px;box-shadow:0 6px 18px rgba(0,0,0,.12)}
.menu.on .dd{display:block}.dd button{display:block;width:100%;text-align:left;border:0;background:transparent}
#toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 14px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none}
#toast.on{opacity:.92}
#mirror{position:absolute;visibility:hidden;white-space:pre-wrap;word-wrap:break-word;top:0;left:-9999px}
@media(max-width:820px){#ed.on{flex-direction:column}.right{max-width:none;min-width:0;border-top:1px solid var(--line)}.left{border-right:0;min-height:55vh}}
</style></head><body>
<header><span class="logo">AIRA</span><div id="tabs"></div><button class="g" id="plus" title="Новый документ">＋</button>
<span class="meta">движок __ENGINE__ · модели __MODELS__ · всё локально · лицензия: демо на этом устройстве</span></header>
<main>
<section id="home"><div class="wrap">
 <h2 style="margin:0">Проверка требований</h2>
 <div style="color:var(--mut)">Напишите или вставьте требования, нажмите «Проверить» — AIRA найдёт размытые формулировки, повторы, противоречия и места, которые задела правка. Документ не покидает компьютер.</div>
 <div class="big">
  <button id="hNew"><b>Новый документ</b><small>пустой лист</small></button>
  <button id="hLast"><b>Последний документ</b><small id="hLastT">—</small></button>
  <button id="hSample"><b>Учебный пример</b><small>«Возвраты», с подсказками</small></button>
  <button id="hImp"><b>Импорт Word</b><small>.docx</small></button>
 </div>
 <div class="sec">Документы</div><div class="recent" id="recent"><div style="cursor:default;color:var(--mut)">Пока пусто — начните с учебного примера.</div></div>
</div></section>
<section id="ed">
 <div class="left">
  <div class="bar">
   <input id="title" maxlength="200" placeholder="Название документа">
   <button class="g" id="bH" title="Заголовок раздела (#)">H</button><button class="g" id="bL" title="Пункт списка (-)">•</button>
   <button class="g" id="bU" title="Отменить (Ctrl+Z)">↶</button><button class="g" id="bR" title="Повторить (Ctrl+Y)">↷</button>
   <div class="menu" id="mExp"><button class="g" id="bExp">Экспорт ▾</button><div class="dd">
    <button data-x="docx">Сохранить как .docx</button><button data-x="md">Сохранить как .md</button><button data-x="copy">Скопировать текст</button></div></div>
  </div>
  <div id="notices"></div>
  <textarea id="txt" spellcheck="false" placeholder="# Раздел&#10;- Система должна …&#10;- Срок … составляет … дней.&#10;&#10;Заголовки начинайте с #, пункты — с -. Можно просто вставить текст из Word или Confluence."></textarea>
  <div class="foot"><span id="save">—</span><span id="cnt"></span></div>
 </div>
 <div class="right">
  <div class="checkbox">
   <div style="display:flex;gap:8px;align-items:center"><button class="p" id="bCheck" style="flex:1">Проверить требования</button><button id="bStop" style="display:none">Остановить</button></div>
   <div id="run" style="display:none"><div class="prog"><i id="pbar"></i></div><div style="display:flex;justify-content:space-between;font-size:12px;color:var(--mut)"><span id="stage"></span><span id="clock"></span></div></div>
   <div id="cerr"></div>
   <div class="opts"><label><input type="checkbox" id="optQ" checked> задавать вопросы</label><span style="flex:1"></span><span id="chips"></span></div>
  </div>
  <div class="panel" id="res"></div>
 </div>
</section>
</main>
<input type="file" id="file" accept=".docx" hidden><div id="mirror"></div><div id="toast"></div>
<script>
const STAGES=__STAGES__;
const T={formulation:'Формулировка',duplicate:'Повтор',contradiction:'Противоречие',affected:'Задето правкой'};
const ORDER=['affected','contradiction','duplicate','formulation'];
const $=id=>document.getElementById(id);
let S={docs:[],open:[],active:null,doc:null,dirty:false,saveT:null,job:null,poll:null,more:new Set(),hidden:new Set(JSON.parse(localStorage.getItem('aira-hidden')||'[]'))};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toast(m){const t=$('toast');t.textContent=m;t.classList.add('on');clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('on'),2600)}
async function api(m,p,b){const r=await fetch(p,{method:m,headers:b?{'Content-Type':'application/json'}:{},body:b?JSON.stringify(b):undefined});
 const j=await r.json().catch(()=>({error:'ответ не JSON'}));if(!r.ok)throw new Error(j.error||r.status);return j}
const ago=ts=>{const s=(Date.now()/1000-ts);return s<60?'только что':s<3600?Math.round(s/60)+' мин назад':s<86400?Math.round(s/3600)+' ч назад':new Date(ts*1000).toLocaleDateString('ru')};
const hhmm=ts=>new Date(ts*1000).toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit'});

// --- документы и вкладки ---------------------------------------------------------
async function refresh(){const s=await api('GET','/api/state');S.docs=s.docs;return s}
function session(){api('POST','/api/session',{open:S.open,active:S.active}).catch(()=>{})}
function renderTabs(){$('tabs').innerHTML=S.open.map(id=>{const d=S.docs.find(x=>x.id==id);return `<div class="tab ${id==S.active?'on':''}" data-id="${id}"><span>${esc(d?d.title:'…')}</span><span class="x" data-x="${id}">×</span></div>`}).join('');
 document.querySelectorAll('.tab').forEach(t=>t.onclick=e=>{if(e.target.dataset.x)return closeTab(e.target.dataset.x);openDoc(t.dataset.id)})}
function renderHome(){const r=S.docs;$('recent').innerHTML=r.length?r.map(d=>`<div data-id="${d.id}"><span>${esc(d.title)}${d.sample?'<span class="badge">учебный</span>':''}</span><span style="color:var(--mut);font-size:12px">${d.checked?'проверен · ':''}${ago(d.updated)}</span></div>`).join(''):'<div style="cursor:default;color:var(--mut)">Пока пусто — начните с учебного примера.</div>';
 document.querySelectorAll('#recent div[data-id]').forEach(x=>x.onclick=()=>openDoc(x.dataset.id));
 $('hLastT').textContent=r[0]?r[0].title:'нет документов';$('hLast').disabled=!r[0]}
function showHome(){$('home').style.display='';$('ed').classList.remove('on');S.active=null;renderTabs();renderHome();session()}
async function flush(){if(S.dirty)await saveNow()}
async function openDoc(id){await flush();stopPoll();
 try{S.doc=await api('GET','/api/docs/'+id)}catch(e){toast('Не удалось открыть: '+e.message);S.open=S.open.filter(x=>x!=id);return showHome()}
 if(!S.open.includes(id))S.open.push(id);S.active=id;$('home').style.display='none';$('ed').classList.add('on');
 $('title').value=S.doc.title;$('txt').value=S.doc.text;S.dirty=false;S.more=new Set();setSave('saved');renderTabs();session();notices();renderRes();count();$('txt').focus()}
async function closeTab(id){if(id==S.active)await flush();S.open=S.open.filter(x=>x!=id);if(id==S.active){S.open.length?openDoc(S.open[S.open.length-1]):showHome()}else{renderTabs();session()}}
async function create(body){const d=await api('POST','/api/docs',body);await refresh();openDoc(d.id)}
$('plus').onclick=$('hNew').onclick=()=>create({title:'Новый документ'});
$('hSample').onclick=()=>create({sample:true});
$('hLast').onclick=()=>S.docs[0]&&openDoc(S.docs[0].id);
$('hImp').onclick=()=>$('file').click();
$('file').onchange=async e=>{const f=e.target.files[0];e.target.value='';if(!f)return;
 const b64=await new Promise((ok,no)=>{const r=new FileReader();r.onload=()=>ok(r.result.split(',')[1]);r.onerror=no;r.readAsDataURL(f)});
 try{const d=await api('POST','/api/import',{name:f.name,data:b64});await refresh();openDoc(d.id);toast('Импортировано: '+f.name)}catch(err){toast('Импорт не удался: '+err.message)}};

// --- редактор и сохранение -------------------------------------------------------
function setSave(st,extra){$('save').textContent={saved:'Сохранено'+(S.doc?' · '+hhmm(S.doc.updated||Date.now()/1000):''),saving:'Сохраняю…',dirty:'Есть изменения…',error:'Не сохранилось — черновик держу в браузере. '+(extra||'')}[st]}
function count(){const t=$('txt').value;$('cnt').textContent=`${t.split('\n').filter(l=>l.trim()&&!l.trim().startsWith('#')).length} строк · ${t.length} символов`}
function backup(){try{localStorage.setItem('aira-draft-'+S.active,JSON.stringify({ts:Date.now()/1000,title:$('title').value,text:$('txt').value}))}catch(e){}}
async function saveNow(){clearTimeout(S.saveT);if(!S.doc)return;setSave('saving');
 try{const r=await api('PUT','/api/docs/'+S.doc.id,{title:$('title').value,text:$('txt').value});S.doc.updated=r.updated;S.doc.text=$('txt').value;S.doc.title=$('title').value;
  S.dirty=false;setSave('saved');try{localStorage.removeItem('aira-draft-'+S.doc.id)}catch(e){}
  const d=S.docs.find(x=>x.id==S.doc.id);if(d){d.title=S.doc.title;d.updated=r.updated}renderTabs()}catch(e){setSave('error',e.message)}}
function edited(){S.dirty=true;setSave('dirty');backup();count();clearTimeout(S.saveT);S.saveT=setTimeout(saveNow,700);notices();renderRes(true)}
$('txt').addEventListener('input',edited);$('title').addEventListener('input',edited);
window.addEventListener('beforeunload',e=>{if(S.dirty){backup();e.preventDefault();e.returnValue=''}});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()=='s'){e.preventDefault();saveNow()}
 if((e.ctrlKey||e.metaKey)&&e.key=='Enter'){e.preventDefault();check()}});
function lineOp(prefix){const ta=$('txt'),v=ta.value,a=v.lastIndexOf('\n',ta.selectionStart-1)+1;let b=v.indexOf('\n',ta.selectionEnd);if(b<0)b=v.length;
 const lines=v.slice(a,b).split('\n');const all=lines.every(l=>l.startsWith(prefix));
 const out=lines.map(l=>all?l.slice(prefix.length):(prefix+l.replace(/^(#+\s*|[-*+]\s+)/,''))).join('\n');
 ta.focus();ta.setSelectionRange(a,b);document.execCommand('insertText',false,out)||(ta.setRangeText(out,a,b,'end'),edited())}
$('bH').onclick=()=>lineOp('# ');$('bL').onclick=()=>lineOp('- ');
$('bU').onclick=()=>{$('txt').focus();document.execCommand('undo')};$('bR').onclick=()=>{$('txt').focus();document.execCommand('redo')};
$('bExp').onclick=e=>{e.stopPropagation();$('mExp').classList.toggle('on')};document.addEventListener('click',()=>$('mExp').classList.remove('on'));
document.querySelectorAll('#mExp .dd button').forEach(b=>b.onclick=async()=>{await saveNow();const x=b.dataset.x;
 if(x=='copy'){try{await navigator.clipboard.writeText($('txt').value);toast('Текст скопирован')}catch(e){$('txt').select();document.execCommand('copy');toast('Текст скопирован')}}
 else location.href=`/api/export/${S.doc.id}?fmt=${x}`});

// --- уведомления над редактором ------------------------------------------------------
function notices(){const n=[];if(!S.doc)return;
 try{const b=JSON.parse(localStorage.getItem('aira-draft-'+S.doc.id)||'null');if(b&&b.text!==S.doc.text&&b.ts>S.doc.updated&&!S.dirty)
  n.push(`<div class="notice">Найден несохранённый черновик от ${hhmm(b.ts)}. <button id="nRest">Восстановить</button><button class="g" id="nDrop">Не нужно</button></div>`)}catch(e){}
 if(S.doc.sample)n.push(`<div class="notice info">Учебный пример. Нажмите «Проверить требования». Потом поменяйте «14 дней» на «30 дней» в первом пункте и проверьте повторно — AIRA покажет, что ещё задела правка.</div>`);
 const c=S.doc.check;if(c&&c.text!==$('txt').value)n.push(`<div class="notice">Текст изменён после проверки ${hhmm(c.ts)} — замечания к изменённым местам помечены как устаревшие. <button id="nRe">Проверить повторно</button></div>`);
 $('notices').innerHTML=n.join('');
 if($('nRest'))$('nRest').onclick=()=>{const b=JSON.parse(localStorage.getItem('aira-draft-'+S.doc.id));$('title').value=b.title;$('txt').value=b.text;edited();toast('Черновик восстановлен')};
 if($('nDrop'))$('nDrop').onclick=()=>{localStorage.removeItem('aira-draft-'+S.doc.id);notices()};
 if($('nRe'))$('nRe').onclick=check}

// --- проверка ---------------------------------------------------------------------
function stopPoll(){clearInterval(S.poll);S.poll=null;S.job=null;running(false)}
function running(on){$('bCheck').disabled=on;$('bStop').disabled=false;$('bStop').textContent='Остановить';$('bStop').style.display=on?'':'none';$('run').style.display=on?'':'none';$('txt').readOnly=false;
 $('bCheck').textContent=on?'Проверяю…':(S.doc&&S.doc.check?'Проверить повторно':'Проверить требования')}
async function check(){if(!S.doc||S.job)return;$('cerr').innerHTML='';await saveNow();
 const opts={questions:$('optQ').checked,disabled:[]};
 try{S.job=await api('POST','/api/check',{id:S.doc.id,text:$('txt').value,opts})}catch(e){$('cerr').innerHTML=`<div class="err">${esc(e.message)}</div>`;return}
 const docId=S.doc.id;running(true);tick(S.job);
 S.poll=setInterval(async()=>{if(!S.job)return;let j;try{j=await api('GET','/api/jobs/'+S.job.id)}catch(e){return}tick(j);
  if(j.state=='running')return;const done=j;stopPoll();
  if(done.state=='done'){if(S.doc&&S.doc.id==docId){S.doc.check=done.result;S.doc.versions=S.doc.versions||[]}await refresh();renderHome();notices();renderRes();
   toast(done.result.partial?'Проверено частично':'Проверка завершена за '+done.result.seconds+' с')}
  else if(done.state=='cancelled'){toast('Анализ остановлен — текст и прошлые результаты сохранены')}
  else $('cerr').innerHTML=`<div class="err">Проверка не удалась: ${esc(done.error)} <button id="eRe">Запустить ещё раз</button></div>`,$('eRe').onclick=check},400)}
function tick(j){$('pbar').style.width=Math.round(j.pct*100)+'%';$('stage').textContent=j.stage_ru||STAGES[j.stage]||'';const s=Math.floor(j.elapsed);
 $('clock').textContent=`${Math.floor(s/60)}:${String(s%60).padStart(2,'0')} из ${j.limit/60}:00`}
$('bCheck').onclick=check;$('bStop').onclick=async()=>{if(!S.job)return;$('bStop').disabled=true;$('bStop').textContent='Останавливаю…';
 try{await api('POST','/api/jobs/'+S.job.id+'/cancel')}catch(e){}};
$('optQ').onchange=()=>renderRes();

// --- результаты --------------------------------------------------------------------
function renderRes(soft){const box=$('res'),c=S.doc&&S.doc.check;if(!c){box.innerHTML=`<div class="empty">Нажмите «Проверить требования» или Ctrl+Enter.<br>Проверяются формулировки, повторы, противоречия; после правки — что ещё она задела.</div>`;$('chips').innerHTML='';running(!!S.job);return}
 if(!soft)running(!!S.job);
 const cur=$('txt').value,all=[...c.impact.map(x=>({...x,type:'affected'})),...c.issues];
 const counts={};all.forEach(x=>counts[x.type]=(counts[x.type]||0)+1);
 $('chips').innerHTML=ORDER.filter(t=>counts[t]).map(t=>`<button class="chip ${S.hidden.has(t)?'off':''}" data-t="${t}">${T[t]} ${counts[t]}</button>`).join('');
 document.querySelectorAll('.chip').forEach(b=>b.onclick=()=>{const t=b.dataset.t;S.hidden.has(t)?S.hidden.delete(t):S.hidden.add(t);localStorage.setItem('aira-hidden',JSON.stringify([...S.hidden]));renderRes(true)});
 let h=`<div style="font-size:12px;color:var(--mut)">Проверено ${hhmm(c.ts)} · ${c.checked.active} пунктов${c.checked.skipped_status?`, пропущено ${c.checked.skipped_status} (архив, черновики, обсуждения)`:''} · ${c.seconds} с</div>`;
 if(c.partial)h+=`<div class="notice" style="margin:8px 0">Проверка частичная: ${esc(c.partial)}.</div>`;
 const vis=all.filter(x=>!S.hidden.has(x.type));
 if(!all.length)h+=`<div class="empty"><b>Замечаний нет</b>Формулировки, повторы и противоречия между похожими пунктами в порядке.<br>Это не гарантия — проверьте смысл сами.</div>`;
 for(const t of ORDER){const xs=vis.filter(x=>x.type==t);if(!xs.length)continue;
  h+=`<div class="sec">${t=='affected'?'Правка задела другие места':{contradiction:'Противоречия',duplicate:'Повторы',formulation:'Формулировки'}[t]}</div>`;
  if(t=='affected')h+=c.changes.map(ch=>`<div style="font-size:12px;color:var(--mut)">Было: «${esc(ch.old)}»<br>Стало: «${esc(ch.new)}»</div>`).join('<br>');
  const lim=S.more.has(t)?xs.length:8;h+=xs.slice(0,lim).map(x=>card(x,cur)).join('');
  if(xs.length>lim)h+=`<button class="g more" data-t="${t}" style="width:100%;color:var(--acc)">Показать ещё ${xs.length-lim}</button>`}
 if($('optQ').checked){const qs=[...new Set(vis.filter(x=>x.question&&cur.includes(x.span.quote)).map(x=>x.question))];if(qs.length)h+=`<div class="sec">Что уточнить</div>`+qs.map(q=>`<div style="font-style:italic;font-size:13px;margin:4px 0">• ${esc(q)}</div>`).join('')}
 box.innerHTML=h;document.querySelectorAll('.iss').forEach(el=>el.onclick=()=>goTo(el.dataset.q));
 document.querySelectorAll('.more').forEach(b=>b.onclick=()=>{S.more.add(b.dataset.t);renderRes(true)})}
function card(x,cur){const old=!cur.includes(x.span.quote);const conf=x.type=='formulation'?'правило':(x.light=='red'?'уверенно':'проверьте');
 const rel=x.related?`<div class="rel">${x.type=='affected'?'из-за правки':'↔'} ${esc(x.related.fragment_id)}: «${esc(x.related.quote)}»</div>`:'';
 const fix=x.suggestion?`<div class="fix">Как исправить: «${esc(x.suggestion.before)}» → ${esc(x.suggestion.after)}</div>`:'';
 const ask=x.question&&$('optQ').checked?`<div class="ask">${esc(x.question)}</div>`:'';
 return `<div class="iss ${old?'old':x.light}" data-q="${esc(x.span.quote)}"><div class="h"><b>${T[x.type]}</b><span class="pill ${x.light=='red'?'r':'y'}">${conf}</span>${x.type!='formulation'?`<span>${Math.round(x.confidence*100)}%</span>`:''}${old?'<span>устарело — текст изменился</span>':''}${x.rule?`<span>${esc(x.rule)}</span>`:''}</div>
 <div class="q">«${esc(x.span.quote)}»</div><div class="ex">${esc(x.explanation)}</div>${fix}${ask}${rel}</div>`}
function goTo(q){const ta=$('txt'),i=ta.value.indexOf(q);if(i<0)return toast('Этого текста уже нет — проверьте повторно');
 const m=$('mirror'),cs=getComputedStyle(ta);['font','padding','width','lineHeight','letterSpacing','boxSizing'].forEach(p=>m.style[p]=cs[p]);m.style.width=ta.clientWidth+'px';
 m.textContent=ta.value.slice(0,i);const y=m.scrollHeight;ta.focus();ta.setSelectionRange(i,i+q.length);ta.scrollTop=Math.max(0,y-ta.clientHeight/3)}

// --- старт ---------------------------------------------------------------------------
(async()=>{const s=await refresh();S.open=(s.session.open||[]).filter(id=>S.docs.some(d=>d.id==id));renderHome();
 if(s.session.active&&S.open.includes(s.session.active))openDoc(s.session.active);else showHome()})();
</script></body></html>"""


if __name__ == "__main__":
    main()
