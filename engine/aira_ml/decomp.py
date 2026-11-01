"""Данные на декомпозицию (v4): верхнеуровневое требование → детальные, которые его реализуют.

    python -m aira_ml.decomp --n 30

Зачем: своя модель выучила «правило изменилось → где повторяется старое значение», но не
связь «верхнее требование → его детализация» без общих слов (провал на D12). Здесь связь —
только по смыслу.

На каждый домен — 4 верхних требования × 5 детальных + реалистичная правка верхнего и
разметка, какие детальные она задевает. Из этого:
1) пространство *-v4.json в формате стенда: source = верхнее, change = правка,
   mentions = задетые детальные, traps = незадетые детальные той же ветки и детальные
   соседней ветки → дальше учитель (teacher.py) как для v2/v3;
2) пары трассировки pairs_v4_trace.jsonl без учителя: «требование будет изменено» (без текста
   правки, как в D12) → все его детальные = нужно обновить, детальные других веток = не связано.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from .generate import DOMAINS, DOMAINS_MORE, OUT, TYPE_CODE, ask, changed_terms, extract_json
from .llm import GigaChatBackend, load_env
from .spaces import load as load_space

ROOT = Path(__file__).resolve().parent.parent
TRACE = ROOT / "data" / "train" / "pairs_v4_trace.jsonl"
GENERIC = " (требование будет изменено)"

PROMPT_DECOMP = """Ты опытный системный аналитик. Модуль: «{domain}».
Опиши 4 разных верхнеуровневых требования этого модуля (бизнес-требования или крупные функции).
Для каждого — 5 детальных требований, которые его реализуют, разных типов: функциональное требование,
поле API, шаг use case, критерий приёмки, статусная модель, текст для клиента, нефункциональное требование.
По одному-два предложения, конкретно, по-русски, как в настоящей спецификации.

Важно: детальные требования НЕ повторяют слова верхнего — связь только по смыслу (это его реализация).
Для каждого верхнего требования придумай одно реалистичное изменение (change — новый полный текст верхнего
требования) и укажи номера его детальных требований (1–5), которые после этого изменения нужно пересмотреть
(affected, от 2 до 4); остальные его не касаются.

Ответь только JSON:
{{"high": [{{"type": "бизнес-требование", "document": "Бизнес-требования", "text": "...", "change": "...",
  "affected": [1, 3], "details": [{{"type": "...", "document": "...", "text": "..."}}]}}]}}"""


def build(slug, domain, prefix, backend):
    raw = OUT / "_raw"
    d = extract_json(ask(backend, PROMPT_DECOMP.format(domain=domain), raw / f"{slug}.v4.txt"))
    counters, fragments, facts, branches = {}, [], [], []

    def add(f):
        code = TYPE_CODE.get(f.get("type", ""), "FRG")
        counters[code] = counters.get(code, 0) + 1
        fid = f"{prefix}-{code}-{counters[code]:02d}"
        fragments.append({"id": fid, "type": f.get("type", "фрагмент"), "document": f.get("document", ""),
                          "status": "active", "links": [], "text": str(f["text"]).strip()})
        return fid

    for h in d.get("high", [])[:4]:
        details = [x for x in h.get("details", []) if isinstance(x, dict) and x.get("text")][:5]
        if not h.get("text") or not h.get("change") or len(details) < 3:
            continue
        src = add({"type": h.get("type", "бизнес-требование"), "document": h.get("document", "Бизнес-требования"),
                   "text": h["text"]})
        kids = [add(x) for x in details]
        aff = {int(i) for i in h.get("affected", []) if str(i).isdigit() and 1 <= int(i) <= len(kids)}
        branches.append({"source": src, "change": str(h["change"]).strip(), "kids": kids,
                         "affected": [kids[i - 1] for i in sorted(aff)]})
    rnd = random.Random(slug)
    for n, b in enumerate(branches, 1):
        if not b["affected"]:
            continue
        others = [k for o in branches if o is not b for k in o["kids"]]
        traps = {k: "та же ветка, правка не касается" for k in b["kids"] if k not in b["affected"]}
        traps |= {k: "другая ветка" for k in rnd.sample(others, min(2, len(others)))}
        old = next(f["text"] for f in fragments if f["id"] == b["source"])
        facts.append({"id": f"F{n}", "name": old[:60], "source": b["source"], "change": b["change"],
                      "search_terms": changed_terms(old, b["change"]) or [old.split()[0]],
                      "mentions": {k: "детализирует" for k in b["affected"]}, "soft": {}, "traps": traps})
    space = {"id": f"gen4-{slug}", "domain": domain, "source": "synthetic-llm-decomposition", "generator": backend.name,
             "split": "train", "note": "Декомпозиция: верхнее требование → детальные. Только для обучения.",
             "fragments": fragments, "facts": facts}
    path = OUT / f"{slug}-v4.json"
    path.write_text(json.dumps(space, ensure_ascii=False, indent=1), encoding="utf-8")
    _, _, errors = load_space(path)
    # пары трассировки без текста правки (как в D12)
    rows = []
    frag = {f["id"]: f for f in fragments}
    for b in branches:
        old = frag[b["source"]]["text"]
        others = [k for o in branches if o is not b for k in o["kids"]]
        for k in b["kids"]:
            rows.append({"old": old, "new": old + GENERIC, "fragment": frag[k], "label": "update", "space": space["id"]})
        for k in rnd.sample(others, min(3, len(others))):
            rows.append({"old": old, "new": old + GENERIC, "fragment": frag[k], "label": "unrelated", "space": space["id"]})
    return path, len(fragments), len(facts), errors, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--start", type=int, default=0)
    a = ap.parse_args()
    load_env()
    import os
    os.environ["AIRA_GIGACHAT_MODEL"] = os.getenv("AIRA_GEN_MODEL", "GigaChat-2-Max")
    backend = GigaChatBackend()
    trace = []
    for slug, domain, prefix in (DOMAINS + DOMAINS_MORE)[a.start:a.start + a.n]:
        try:
            path, nf, nfact, errors, rows = build(slug, domain, prefix, backend)
            trace += rows
            print(f"{slug}: фрагментов {nf}, веток {nfact}, пар трассировки {len(rows)}, ошибок {len(errors)}", flush=True)
        except Exception as e:
            print(f"{slug}: ОШИБКА {type(e).__name__}: {str(e)[:160]}", flush=True)
    TRACE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in trace), encoding="utf-8")
    print("пар трассировки:", len(trace), "→", TRACE)


if __name__ == "__main__":
    main()
