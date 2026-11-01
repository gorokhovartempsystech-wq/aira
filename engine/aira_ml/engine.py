"""Движок AIRA для десктопа: ревью документа и влияние правки. Без PyTorch.

    python -m aira_ml.engine serve  --models dist/models-0.1 [--port 8765]
    python -m aira_ml.engine review  файл.md|docx  --models dist/models-0.1
    python -m aira_ml.engine impact  файл.md --id F007 --new "новый текст" --models dist/models-0.1

Зависимости рантайма: numpy, onnxruntime, tokenizers и стандартная библиотека. Модели —
пакет из pack.py (ONNX int8). Всё работает локально: документы никуда не уходят.

Сервер слушает только 127.0.0.1 и требует заголовок X-Aira-Token. Токен печатается при
старте первой строкой JSON — приложение, которое запустило движок, читает его из stdout.
Так страница в браузере пользователя не сможет обратиться к движку.

Контракт ответа — список замечаний (issues):
  id, type, severity, confidence (0–1, после калибровки), light (red | yellow),
  fragment_id, span {start, end, quote} — позиции внутри текста фрагмента,
  related {fragment_id, quote, status} | null, explanation, rule | null,
  suggestion {before, after} | null, question | null
Типы: formulation, duplicate, contradiction, affected.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from .lint import lint

VERSION = "0.1.0"
STATUS_RU = {"active": "действует", "exception": "исключение", "deprecated": "архив",
             "delta": "черновик доработки", "discussion": "обсуждение"}
SKIP = {"deprecated", "delta", "discussion"}
FLAG = {"contradiction", "update"}
TYPES = ("formulation", "duplicate", "contradiction", "affected")

# пороги — стартовые, уточнять на размеченных данных
DUP_RED, DUP_YELLOW = 0.97, 0.94         # косинус эмбеддингов; 0.90–0.93 на реальных ТЗ — почти всегда разные пункты
NLI_RED, NLI_YELLOW = 0.95, 0.85         # «противоречит» в ОБЕ стороны (NLI); общий NLI шумит — порог высокий
PAIR_RED = 0.60                          # уверенность «затронуто» для красного
K_MEANING, K_NLI = 8, 3

_WORD = re.compile(r"[\w%-]+", re.UNICODE)
QUESTION = {
    "VAGUE": "Какое измеримое значение подразумевается под «{q}»?",
    "ESCAPE": "При каких условиях «{q}» — обязательно или нет?",
    "OPEN_END": "Что ещё входит в перечень, который заканчивается «{q}»?",
    "AND_OR": "Нужно выполнить оба условия или достаточно одного?",
}
AFTER = {"VAGUE": "<измеримое значение>", "ESCAPE": "<условие, когда требование обязательно>",
         "OPEN_END": "<полный перечень>", "AND_OR": "<«и» или «или»>"}


# --- модели ------------------------------------------------------------------

class Onnx:
    def __init__(self, folder, threads):
        self.tok = Tokenizer.from_file(str(Path(folder) / "tokenizer.json"))
        self.tok.enable_truncation(256)
        self.tok.enable_padding()
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(str(Path(folder) / "model.int8.onnx"), so, providers=["CPUExecutionProvider"])
        self.names = {i.name for i in self.sess.get_inputs()}

    def run(self, a, b=None, bs=32):
        out = []
        for i in range(0, len(a), bs):
            enc = self.tok.encode_batch(a[i:i + bs] if b is None else list(zip(a[i:i + bs], b[i:i + bs])))
            feed = {"input_ids": np.array([e.ids for e in enc], np.int64),
                    "attention_mask": np.array([e.attention_mask for e in enc], np.int64),
                    "token_type_ids": np.array([e.type_ids for e in enc], np.int64)}
            out.append(self.sess.run(None, {k: v for k, v in feed.items() if k in self.names})[0])
        return np.concatenate(out) if out else np.zeros((0, 1), np.float32)


BOILERPLATE = re.compile(r"(?i)^(требования\s+не\s+предъявляются|не\s+требуется|не\s+предусмотрен[оаы]?|отсутству(ет|ют)"
                         r"|не\s+применяется|в\s+соответствии\s+с\s+[^.]{0,40})\.?$")
_TABLE_ROW = re.compile(r"\s\|\s")
# перечень нормативных ссылок: названия стандартов похожи друг на друга, но это разные документы, а не повторы
NORMATIVE = re.compile(r"(?i)^[«\"]?\s*(ГОСТ|ISO|IEC|IEEE|СНиП|СП\s\d|РД\s|СанПиН|Федеральн\w+ закон|Постановлени|Приказ|Указ\b"
                       r"|Распоряжени|Методическ\w+ документ|Руководящ\w+ документ)|\b№\s?\d+-ФЗ\b|[»\"],?\s+утвержд\w+")
# договорная часть ТЗ на закупку: оплата, гарантия, приёмка, санкции — условия договора, а не требования к системе;
# «аванс 30 %» и «остаток 70 %» модель принимала за противоречие
CONTRACT = re.compile(r"(?i)\bаванс|\bоплат[аыуие]|\bоплачива|гарантийн\w+ срок|неустойк|\bштраф|\bпени\b|банковск\w+ дн"
                      r"|сдачи[-–]при[её]мк|акт\w* (об оказанных|сдачи|при[её]ма)|цен\w+ (договора|контракта)"
                      r"|срок\w* (выполнения|оказания) (работ|услуг)|мотивированн\w+ отказ")
# сторона договора: без неё «оплата» — это функция системы («пользователь оплачивает заказ картой»)
PARTY = re.compile(r"(?i)\bзаказчик|\bисполнител|\bподрядчик|\bпоставщик|\bсторон[аыуе]?\b|\bдоговор|\bконтракт")


def checkable(f):
    """Можно ли проверять пункт на повторы и противоречия. На реальных ТЗ (dedoc, 44 документа) почти весь
    шум давали не требования: строки таблиц, вводки с двоеточием, шаблонные «Требования не предъявляются»,
    короткие строки перечней (адреса, названия). Формулировки (lint) проверяются у всех пунктов."""
    t = f["text"].strip()
    if len(t) < 30 or t.endswith(":") or BOILERPLATE.match(t) or NORMATIVE.search(t):
        return False
    if (CONTRACT.search(t) and PARTY.search(t)) or CONTRACT.search(f.get("document", "")):
        return False
    if _TABLE_ROW.search(t):                          # строка таблицы: «№ | наименование | ед. | кол-во»
        cells = [c.strip() for c in t.split("|")]
        if len(cells) >= 3 or sum(bool(re.fullmatch(r"[\d\s.,%№\-–()]+", c)) for c in cells) >= 1:
            return False
    return True


def siblings(a, b):
    """Соседние однотипные пункты (поля одного API, строки одного маппинга, элементы одного перечня): разные
    значения у разных сущностей — это не противоречие, а структура. Один документ и тип, и либо общий
    префикс ≥ 15 символов, либо оба коротких пункта (< 90 символов) без «должен/обязан» — элементы перечня."""
    if a.get("document") != b.get("document") or a.get("type") != b.get("type"):
        return False
    n = 0
    for x, y in zip(a["text"], b["text"]):
        if x != y:
            break
        n += 1
    if n >= 15:
        return True
    short = lambda t: len(t) < 90 and not re.search(r"(?i)\bдолж|\bобязан|\bнеобходимо|\bзапрещ|\bне\s+допуска", t)
    return short(a["text"]) and short(b["text"])


class Cancelled(Exception):
    """Пользователь остановил анализ: progress-колбэк бросает это исключение."""


def softmax(x, t=1.0):
    z = x / t
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


class Engine:
    def __init__(self, models, threads=4):
        self.dir = Path(models)
        self.manifest = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        m = self.manifest["models"]
        t = time.time()
        self.emb = Onnx(self.dir / "embedder", threads)
        self.pair = Onnx(self.dir / "pair", threads)
        self.nli = Onnx(self.dir / "nli", threads)
        self.pair_labels, self.pair_t = m["pair"]["labels"], m["pair"].get("temperature", 1.0)
        self.nli_labels = m["nli"]["labels"]
        self.load_s = round(time.time() - t, 2)

    # --- разбор текста ----------------------------------------------------------

    @staticmethod
    def parse_text(text, doc="Документ"):
        """Абзацы и пункты → фрагменты со смещением в исходном тексте. Заголовки задают
        документ-раздел; по нему и по маркерам определяется статус."""
        frags, section, pos = [], doc, 0
        for raw in re.split(r"\n", text):
            line = raw.strip()
            start = text.find(raw, pos)
            pos = start + len(raw) if start >= 0 else pos
            if not line:
                continue
            if line.startswith("#"):
                section = line.lstrip("# ").strip() or doc
                continue
            body = re.sub(r"^([-*+]|\d+[.)])\s+", "", line)
            if len(body) < 12:
                continue
            frags.append({"id": f"F{len(frags) + 1:03d}", "text": body, "document": section,
                          "status": Engine.guess_status(section, body), "type": Engine.guess_type(body),
                          "offset": start + raw.find(body)})
        return frags

    @staticmethod
    def guess_status(section, text):
        s = (section + " " + text[:40]).lower()
        if "обсуждается" in s or "обсуждение" in section.lower():
            return "discussion"
        if "архив" in s or "устарел" in s:
            return "deprecated"
        if "черновик" in s or section.lower().startswith("доработк"):
            return "delta"
        if text.lower().startswith(("исключение", "кроме")):
            return "exception"
        return "active"

    @staticmethod
    def guess_type(text):
        t = text.lower()
        if t.startswith("как ") and "я хочу" in t:
            return "user story"
        if re.match(r"шаг \d", t):
            return "шаг use case"
        if re.search(r"\b(get|post|put|patch|delete) /|\bполе\b|`", t):
            return "поле API"
        if t.startswith(("дано", "если", "когда")) and ("то " in t or "тогда" in t):
            return "критерий приёмки"
        if "должн" in t:
            return "функциональное требование"
        return "фрагмент"

    def parse_file(self, path):
        p = Path(path)
        if p.suffix.lower() == ".docx":
            from .realdocs import docx_blocks
            text = "\n".join(("# " + b[2:]) if b.startswith("# ") else b for b in docx_blocks(p))
        else:
            text = p.read_text(encoding="utf-8", errors="replace")
        return self.parse_text(text, p.stem)

    # --- ревью ---------------------------------------------------------------------

    @staticmethod
    def _id(*parts):
        return "iss-" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]

    def embed(self, frags):
        return self.emb.run([f["text"] for f in frags])

    def review(self, frags, disabled=(), dismissed=(), progress=None, deadline=None):
        """progress(stage, доля 0–1) вызывается между этапами и внутри проверки логики; чтобы остановить
        анализ, колбэк бросает Cancelled. deadline — время (time.time()), после которого проверка логики
        прерывается и ответ помечается partial: часть пар не проверена."""
        t = time.time()
        step = progress or (lambda stage, pct: None)
        issues = []
        partial = None
        active = [f for f in frags if f.get("status", "active") not in SKIP]
        # 1) формулировки — правила
        step("formulation", 0.05)
        for f in active:
            for rule, s, e, q in lint(f["text"]):
                issues.append({"id": self._id("formulation", f["id"], rule.code, s), "type": "formulation",
                               "severity": rule.severity, "confidence": 1.0, "light": "red", "fragment_id": f["id"],
                               "span": {"start": s, "end": e, "quote": q}, "related": None,
                               "explanation": rule.explanation, "rule": f"ISO/IEC/IEEE 29148: {rule.property}",
                               "suggestion": {"before": q, "after": AFTER.get(rule.code, "<уточнить>")},
                               "question": QUESTION.get(rule.code, "").format(q=q) or None})
        # 2) дубли и 3) противоречия — по близости эмбеддингов, только среди пунктов-требований
        n_active = len(active)
        active = [f for f in active if checkable(f)]
        if len(active) > 1 and ("duplicate" not in disabled or "contradiction" not in disabled):
            step("duplicate", 0.2)
            v = self.embed(active)
            sim = v @ v.T
            np.fill_diagonal(sim, -1)
            seen = set()
            pairs = []
            for i in range(len(active)):
                for j in np.argsort(-sim[i])[:K_NLI]:
                    a, b = sorted((i, int(j)))
                    if (a, b) in seen or sim[a, b] < 0.5:
                        continue
                    seen.add((a, b))
                    pairs.append((a, b, float(sim[a, b])))
            nli_p = None
            if pairs and "contradiction" not in disabled:
                ci, chunk, done = self.nli_labels.index("contradiction"), 32, []
                for k in range(0, len(pairs), chunk):
                    if deadline and time.time() > deadline:
                        partial = f"не хватило времени: логика проверена для {k} из {len(pairs)} пар похожих пунктов"
                        break
                    step("logic", 0.3 + 0.65 * k / len(pairs))
                    part = pairs[k:k + chunk]
                    prem = [active[a]["text"] for a, b, _ in part] + [active[b]["text"] for a, b, _ in part]
                    hyp = [active[b]["text"] for a, b, _ in part] + [active[a]["text"] for a, b, _ in part]
                    pr = softmax(self.nli.run(prem, hyp))[:, ci]
                    done.append(np.minimum(pr[:len(part)], pr[len(part):]))   # противоречие симметрично
                nli_p = np.concatenate(done) if done else np.zeros(0)
            step("questions", 0.97)
            for n, (a, b, s) in enumerate(pairs):
                fa, fb = active[a], active[b]
                if s >= DUP_YELLOW and "duplicate" not in disabled:
                    issues.append({"id": self._id("duplicate", fa["id"], fb["id"]), "type": "duplicate",
                                   "severity": "info", "confidence": round(s, 3), "light": "red" if s >= DUP_RED else "yellow",
                                   "fragment_id": fb["id"], "span": {"start": 0, "end": len(fb["text"]), "quote": fb["text"]},
                                   "related": {"fragment_id": fa["id"], "quote": fa["text"], "status": fa.get("status", "active")},
                                   "explanation": "Почти то же самое уже сказано в другом месте.", "rule": None,
                                   "suggestion": None, "question": "Оставить одно из двух требований или они о разном?"})
                elif (nli_p is not None and n < len(nli_p) and nli_p[n] >= NLI_YELLOW and not siblings(fa, fb)
                      and "exception" not in (fa.get("status"), fb.get("status"))):
                    p = float(nli_p[n])
                    issues.append({"id": self._id("contradiction", fa["id"], fb["id"]), "type": "contradiction",
                                   "severity": "critical", "confidence": round(p, 3), "light": "red" if p >= NLI_RED else "yellow",
                                   "fragment_id": fb["id"], "span": {"start": 0, "end": len(fb["text"]), "quote": fb["text"]},
                                   "related": {"fragment_id": fa["id"], "quote": fa["text"], "status": fa.get("status", "active")},
                                   "explanation": "Два действующих требования, похоже, нельзя выполнить одновременно.",
                                   "rule": "ISO/IEC/IEEE 29148: непротиворечивость набора", "suggestion": None,
                                   "question": "Какое из двух правил действует?"})
        issues = [x for x in issues if x["type"] not in disabled and x["id"] not in set(dismissed)]
        return {"engine": VERSION, "models": self.manifest["version"], "issues": issues,
                "questions": sorted({x["question"] for x in issues if x.get("question")}),
                "checked": {"fragments": len(frags), "active": n_active, "skipped_status": len(frags) - n_active,
                            "pairwise": len(active)},
                "partial": partial, "seconds": round(time.time() - t, 2)}

    # --- влияние правки (H1) -------------------------------------------------------------

    @staticmethod
    def changed_terms(old, new, k=2):
        new_words = {w.lower() for w in _WORD.findall(new)}
        diff = [w for w in _WORD.findall(old) if w.lower() not in new_words and len(w) > 1]
        diff.sort(key=lambda w: (not any(c.isdigit() for c in w), "_" not in w and "«" not in w))
        return [w.strip("«»") for w in diff[:k]]

    def impact(self, frags, new, fragment_id=None, old=None):
        t = time.time()
        by = {f["id"]: f for f in frags}
        if fragment_id in by:
            src = by[fragment_id]
        else:
            src = max(frags, key=lambda f: difflib.SequenceMatcher(None, f["text"], old or "").ratio())
        old = src["text"]
        terms = self.changed_terms(old, new) or [old[:30]]
        rx = [re.compile(rf"(?<![\w]){re.escape(x.lower())}(?![\w])") for x in terms]
        words = {f["id"] for f in frags if f["id"] != src["id"] and any(r.search(f["text"].lower()) for r in rx)}
        pool = [f for f in frags if f["id"] != src["id"] and f.get("status", "active") not in SKIP]
        cands = []
        if pool:
            v = self.emb.run([src["text"]] + [f["text"] for f in pool])
            sim = v[1:] @ v[0]
            top = [pool[j]["id"] for j in np.argsort(-sim)[:K_MEANING]]
            cands = [i for i in dict.fromkeys(sorted(words & {f["id"] for f in pool}) + top)]
        issues = []
        if cands:
            a = [f"Было: {old}\nСтало: {new}"] * len(cands)
            b = [f"[{by[i].get('type', 'фрагмент')}; {STATUS_RU.get(by[i].get('status', 'active'), 'действует')}] {by[i]['text']}"
                 for i in cands]
            pr = softmax(self.pair.run(a, b), self.pair_t)
            for i, p in zip(cands, pr):
                lab = self.pair_labels[int(p.argmax())]
                pflag = float(sum(p[self.pair_labels.index(x)] for x in FLAG))
                if lab in FLAG:
                    light = "red" if pflag >= PAIR_RED else "yellow"
                elif i in words:
                    light = "yellow"
                else:
                    continue
                f = by[i]
                issues.append({"id": self._id("affected", src["id"], i, new), "type": "affected",
                               "severity": "critical" if lab == "contradiction" else "warning",
                               "confidence": round(pflag, 3), "light": light, "fragment_id": i,
                               "span": {"start": 0, "end": len(f["text"]), "quote": f["text"]},
                               "related": {"fragment_id": src["id"], "quote": old, "status": src.get("status", "active")},
                               "explanation": {"contradiction": "После правки противоречит новому значению.",
                                               "update": "Повторяет или выводит старое значение — нужно обновить."}.get(
                                   lab, "Совпадает по словам, но модель считает, что можно не трогать — проверьте."),
                               "rule": None, "suggestion": None, "question": None})
        issues.sort(key=lambda x: (x["light"] != "red", -x["confidence"]))
        return {"engine": VERSION, "models": self.manifest["version"], "source": src["id"], "old": old, "new": new,
                "search_terms": terms, "issues": issues,
                "checked": {"fragments": len(frags), "candidates": len(cands),
                            "skipped_status": sum(1 for f in frags if f.get("status") in SKIP)},
                "seconds": round(time.time() - t, 2)}


# --- HTTP для приложения ---------------------------------------------------------------

def serve(engine, port):
    token = secrets.token_urlsafe(24)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, data):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _ok(self):
            if self.headers.get("X-Aira-Token") != token:
                self._send(401, {"error": "нет или неверный X-Aira-Token"})
                return False
            return True

        def do_GET(self):
            if not self._ok():
                return
            if self.path == "/health":
                return self._send(200, {"status": "ok", "engine": VERSION, "models": engine.manifest["version"],
                                        "load_s": engine.load_s})
            self._send(404, {"error": "не найдено"})

        def do_POST(self):
            if not self._ok():
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 5_000_000:
                    return self._send(413, {"error": "слишком большой документ"})
                d = json.loads(self.rfile.read(n) or b"{}")
                frags = d.get("fragments") or engine.parse_text(d.get("text", ""))
                if self.path == "/v1/parse":
                    return self._send(200, {"fragments": frags})
                if self.path == "/v1/review":
                    return self._send(200, engine.review(frags, d.get("disabled_types", []), d.get("dismissed", [])))
                if self.path == "/v1/impact":
                    return self._send(200, engine.impact(frags, d["new"], d.get("fragment_id"), d.get("old")))
                self._send(404, {"error": "не найдено"})
            except (KeyError, ValueError) as e:
                self._send(400, {"error": f"неверный запрос: {e}"})

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(json.dumps({"ready": True, "port": port, "token": token}), flush=True)
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "review", "impact"):
        s = sub.add_parser(name)
        s.add_argument("--models", required=True)
        s.add_argument("--threads", type=int, default=4)
        if name == "serve":
            s.add_argument("--port", type=int, default=8765)
        else:
            s.add_argument("file")
        if name == "impact":
            s.add_argument("--id")
            s.add_argument("--old")
            s.add_argument("--new", required=True)
    a = ap.parse_args()
    eng = Engine(a.models, a.threads)
    if a.cmd == "serve":
        serve(eng, a.port)
        return
    frags = eng.parse_file(a.file)
    res = eng.review(frags) if a.cmd == "review" else eng.impact(frags, a.new, a.id, a.old)
    json.dump(res, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
