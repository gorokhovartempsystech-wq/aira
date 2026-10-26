"""Реальная проверка на D12 (High-Level to Low-Level Requirements Coverage, Zenodo 10817760, CC BY 4.0).

    python -m aira_ml.coverage <папка с *_original.csv> [--k 8] [--judge gigachat] [--md отчёт.md]

Постановка — прокси для H1. Пять реальных проектов (CM1, CCHIT, GANTT, InfusionPump,
WARC). У каждого требования верхнего уровня (HLR) размечены детальные требования (LLR),
которые его реализуют. Если HLR меняется, затронуты именно они. Задача та же, что
на стенде: среди всех LLR проекта найти связанные с изменённым HLR.

Отличия от стенда (их нужно оговаривать в методике):
- содержания правки нет — известно только, какое требование меняется. Поэтому
  «поиск по словам» здесь — ранжирование BM25 по словам HLR (поиск в Confluence
  по ключевым словам), а классификатор отвечает на вопрос «зависит ли LLR от HLR»
  (промпт PROMPT_DEP), а не «противоречит / нужно обновить»;
- статусов и связей нет — лестница сокращается до «слова → смысл → слова + смысл →
  + классификатор»;
- тексты на английском, а модели (USER-bge-m3, классификатор) настраивались на
  русском — заодно проверка переноса.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np

K = 8
_TOK = re.compile(r"\w+", re.UNICODE)
STOP = set("""a an the of to and or in on for with by be is are shall will should must may can this that
these those it its as at from into all any each such which when if then than not no only also both
system ability provide provides able
и в во на с со по к ко о об от до из за для не ни а но или что это как если то же бы ли при после через
должна должен должны должно система системы обеспечивать обеспечить возможность""".split())

PROMPT_DEP = """You help a systems analyst trace requirements. A high-level requirement is going to be changed.
Decide whether the low-level requirement below depends on it — i.e. it implements, refines or details
the high-level requirement, so it must be reviewed when the high-level requirement changes.

High-level requirement:
{high}

Low-level requirement:
{low}

Answer only JSON: {{"answer": "yes" or "no", "why": "<one sentence>"}}"""


PROMPT_DEP_RU = """Ты помогаешь системному аналитику вести трассировку требований. Требование верхнего уровня собираются изменить.
Реши, зависит ли от него детальное требование ниже — то есть реализует, уточняет или детализирует его, так что его
нужно пересмотреть при изменении верхнего.

Требование верхнего уровня:
{high}

Детальное требование:
{low}

Ответь только JSON: {{"answer": "yes" или "no", "why": "<одно предложение>"}}"""

PROMPT_TR = """Переведи на русский язык требования к программной системе. Сохраняй смысл, термины, числа, идентификаторы,
имена полей и аббревиатуры (их не переводи). Стиль — как в русском ТЗ. Ответь только JSON-массивом строк той же длины
и в том же порядке, без пояснений.

{items}"""


def load(path):
    """HLR → множество LLR. LLR дедуплицируются по тексту внутри проекта."""
    rows = list(csv.DictReader(open(path, encoding="utf-8", errors="replace"), delimiter=";"))
    llr_id, highs = {}, []
    for r in rows:
        lows = [t.strip() for t in (r["low_text"] or "").split("|") if t.strip()]
        ids = set()
        for t in lows:
            ids.add(llr_id.setdefault(t, f"L{len(llr_id) + 1:04d}"))
        highs.append({"id": f"H{len(highs) + 1:03d}", "text": r["high_text"].strip(), "gold": ids})
    lows = {i: t for t, i in llr_id.items()}
    return highs, lows


def toks(text):
    return [t for t in _TOK.findall(text.lower()) if t not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.ids = list(docs)
        self.tf = [Counter(toks(docs[i])) for i in self.ids]
        self.len = np.array([sum(c.values()) for c in self.tf], dtype=float)
        self.avg = self.len.mean() or 1.0
        df = Counter(t for c in self.tf for t in c)
        n = len(self.ids)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query):
        q = set(toks(query))
        s = np.zeros(len(self.ids))
        for j, c in enumerate(self.tf):
            norm = self.k1 * (1 - self.b + self.b * self.len[j] / self.avg)
            s[j] = sum(self.idf[t] * c[t] * (self.k1 + 1) / (c[t] + norm) for t in q if t in c)
        return s

    def top(self, query, k):
        s = self.scores(query)
        return [self.ids[j] for j in np.argsort(-s)[:k] if s[j] > 0]


def run_project(highs, lows, embedder, k, judge=None):
    bm = BM25(lows)
    ids = list(lows)
    lv = embedder.encode([lows[i] for i in ids])
    hv = embedder.encode([h["text"] for h in highs])
    methods = {"1 только слова (BM25)": [], "2 только смысл": [], "3 слова + смысл": []}
    if judge:
        methods |= {"4 + классификатор (🔴)": [], "5 светофор 🔴+🟡": []}
    for h, q in zip(highs, hv):
        w = bm.top(h["text"], k)
        m = [ids[j] for j in np.argsort(-(lv @ q))[:k]]
        hyb = w + [i for i in m if i not in w]
        methods["1 только слова (BM25)"].append((h, w))
        methods["2 только смысл"].append((h, m))
        methods["3 слова + смысл"].append((h, hyb))
        if judge:
            red = [i for i in hyb if judge(h["text"], lows[i])]
            methods["4 + классификатор (🔴)"].append((h, red))
            methods["5 светофор 🔴+🟡"].append((h, red + [i for i in w if i not in red]))
    return methods


def summary(rows):
    g = sum(len(h["gold"]) for h, _ in rows)
    r = sum(len(f) for _, f in rows)
    hit = sum(len(set(f) & h["gold"]) for h, f in rows)
    return {"recall": hit / g if g else 0.0, "precision": hit / r if r else 0.0,
            "returned": r, "gold": g, "hits": hit}


class DepJudge:
    """Классификатор зависимости поверх бэкенда из llm.py, с тем же JSON-кэшем."""

    def __init__(self, kind, lang="en"):
        self.prompt = PROMPT_DEP_RU if lang == "ru" else PROMPT_DEP
        from . import llm
        llm.load_env()
        self.inner = llm.Judge(llm.BACKENDS[kind]())
        self.name = self.inner.name

    def __call__(self, high, low):
        import hashlib
        prompt = self.prompt.format(high=high, low=low)
        key = "dep:" + hashlib.sha1(prompt.encode()).hexdigest()
        c = self.inner.cache
        if key not in c:
            raw = self.inner.backend.chat(prompt)
            m = re.search(r"\{.*\}", raw, re.S)
            try:
                ans = str(json.loads(m.group(0)).get("answer", "")).lower() if m else ""
            except json.JSONDecodeError:
                ans = ""
            c[key] = {"label": "yes" if ans.startswith("y") or ans.startswith("да") else "no", "raw": raw[:300]}
            self.inner.path.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
        return c[key]["label"] == "yes"


class OwnDep:
    """Своя модель (train_cross, 4 класса) как судья зависимости: изменение верхнеуровневого
    требования подаём как «Было: HLR / Стало: HLR (будет изменено)»; «затронуто» = противоречит
    или нужно обновить. Работает через ONNX int8 из пакета движка — тот же путь, что на десктопе."""

    def __init__(self, pack, threads=6):
        from .engine import Engine, softmax
        self.e, self.softmax = Engine(pack, threads), softmax
        self.name = "own:" + Path(pack).name
        self.cache = {}

    def __call__(self, high, low):
        key = (high, low)
        if key not in self.cache:
            a = [f"Было: {high}\nСтало: {high} (требование будет изменено)"]
            b = [f"[требование; действует] {low}"]
            p = self.softmax(self.e.pair.run(a, b), self.e.pair_t)[0]
            lab = self.e.pair_labels[int(p.argmax())]
            self.cache[key] = lab in ("contradiction", "update")
        return self.cache[key]


def cmd_translate(src, dst, model="GigaChat-2-Pro", batch=10):
    """Перевод D12 на русский с кэшем: та же структура CSV (high_text;low_text с «|»)."""
    import os
    from . import llm
    llm.load_env()
    os.environ["AIRA_GIGACHAT_MODEL"] = model
    be = llm.GigaChatBackend()
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    cache_p = dst / "_translations.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else {}
    files = sorted(Path(src).glob("*_original.csv"))
    texts = []
    for f in files:
        for r in csv.DictReader(open(f, encoding="utf-8", errors="replace"), delimiter=";"):
            texts.append(r["high_text"].strip())
            texts += [t.strip() for t in (r["low_text"] or "").split("|") if t.strip()]
    todo = [t for t in dict.fromkeys(texts) if t not in cache]
    print(f"текстов {len(set(texts))}, перевести {len(todo)}", flush=True)
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        for attempt in range(3):
            raw = be.chat(PROMPT_TR.format(items=json.dumps(chunk, ensure_ascii=False)), max_tokens=4000)
            m = re.search(r"\[.*\]", raw, re.S)
            try:
                out = json.loads(m.group(0)) if m else []
            except json.JSONDecodeError:
                out = []
            if len(out) == len(chunk) and all(isinstance(x, str) and x.strip() for x in out):
                break
            if attempt == 2:          # не вышло пачкой — по одному
                out = []
                for t in chunk:
                    r1 = be.chat(PROMPT_TR.format(items=json.dumps([t], ensure_ascii=False)), max_tokens=1500)
                    m1 = re.search(r"\[.*\]", r1, re.S)
                    try:
                        out.append(json.loads(m1.group(0))[0])
                    except Exception:
                        out.append(t)
        for t, ru in zip(chunk, out):
            cache[t] = ru.strip()
        cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"  {min(i + batch, len(todo))}/{len(todo)}", flush=True)
    for f in files:
        rows = list(csv.DictReader(open(f, encoding="utf-8", errors="replace"), delimiter=";"))
        with open(dst / f.name, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["high_text", "low_text"])
            for r in rows:
                lows = [cache.get(t.strip(), t.strip()) for t in (r["low_text"] or "").split("|") if t.strip()]
                w.writerow([cache.get(r["high_text"].strip(), r["high_text"].strip()), "|".join(x.replace("|", "/") for x in lows)])
    print("готово:", dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--k", type=int, default=K)
    ap.add_argument("--judge", help="local | gigachat | openai | own:<папка пакета движка>")
    ap.add_argument("--only", nargs="*", help="проекты, например GANTT WARC")
    ap.add_argument("--embedder", choices=["st", "tfidf"], default="st")
    ap.add_argument("--md")
    ap.add_argument("--lang", default="en", help="язык промпта судьи GigaChat: en | ru")
    ap.add_argument("--translate-to", help="перевести папку на русский в эту папку и выйти")
    a = ap.parse_args()
    if a.translate_to:
        cmd_translate(a.folder, a.translate_to)
        return
    from .embed import STEmbedder, TfidfEmbedder
    emb = STEmbedder() if a.embedder == "st" else TfidfEmbedder()
    judge = (OwnDep(a.judge[4:]) if a.judge and a.judge.startswith("own:") else DepJudge(a.judge, a.lang) if a.judge else None)
    files = sorted(Path(a.folder).glob("*_original.csv"))
    if a.only:
        files = [f for f in files if f.name.split("_")[0] in a.only]
    total, lines = {}, []
    lines.append(f"k = {a.k}, эмбеддер {a.embedder}, классификатор {judge.name if judge else '—'}\n")
    lines.append("| проект | способ | полнота | точность | выдано / эталон |\n|---|---|---|---|---|")
    for f in files:
        name = f.name.split("_")[0]
        highs, lows = load(f)
        res = run_project(highs, lows, emb, a.k, judge)
        for meth, rows in res.items():
            s = summary(rows)
            total.setdefault(meth, []).extend(rows)
            lines.append(f"| {name} ({len(highs)} HLR, {len(lows)} LLR) | {meth} | {s['recall']:.0%} | "
                         f"{s['precision']:.0%} | {s['returned']} / {s['gold']} |")
        print(name, "готово", flush=True)
    lines.append("| **всего** | | | | |")
    for meth, rows in total.items():
        s = summary(rows)
        lines.append(f"| **всего** | {meth} | **{s['recall']:.0%}** | **{s['precision']:.0%}** | {s['returned']} / {s['gold']} |")
    out = "\n".join(lines)
    print(out)
    if a.md:
        Path(a.md).write_text(out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
