"""Анализатор на наборе v5: сколько заложенных дефектов находит и сколько ложных срабатываний на двойниках и «шуме».

    python -m aira_ml.gen5_eval --models dist/models-0.2m

Пока набор не проверен экспертами, это точка отсчёта, а не результат: эталон — разметка генератора.
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import Counter
from pathlib import Path

from .engine import Engine

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "spaces" / "gen5"
NOISE = ("нормативная ссылка", "условие договора", "строка таблицы")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=str(ROOT / "dist" / "models-0.2m"))
    ap.add_argument("--threads", type=int, default=6)
    a = ap.parse_args()
    eng = Engine(a.models, a.threads)
    c, rows = Counter(), []
    for p in sorted(glob.glob(str(SRC / "*-v5.json"))):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        fr = {f["id"]: f for f in d["fragments"]}
        res = eng.review(d["fragments"])
        form = {}
        pairs = {}
        for x in res["issues"]:
            if x["type"] == "formulation":
                form.setdefault(x["fragment_id"], []).append(x["span"]["quote"])
            elif x["type"] == "contradiction":
                pairs[frozenset((x["fragment_id"], x["related"]["fragment_id"]))] = x["light"]
        marked = set()
        for x in d["defects"] + d["twins"]:
            t, ids = x["type"], x["fragments"]
            marked.update(ids)
            c[f"{t}:всего"] += 1
            if t in ("conflict", "conflict_twin"):
                light = pairs.get(frozenset(ids[:2]))
                if light:
                    c[f"{t}:{light}"] += 1
                hit = bool(light)
            else:
                quotes = form.get(ids[0], [])
                hit = bool(quotes)
                if hit and x.get("quote") and any(q.lower() in x["quote"].lower() or x["quote"].lower() in q.lower() for q in quotes):
                    c[f"{t}:в цитату"] += 1
            c[f"{t}:найдено"] += hit
            if x.get("hint"):
                c[f"{t}·пометка:всего"] += 1
                c[f"{t}·пометка:найдено"] += hit
            rows.append({"doc": d["id"], "id": x["id"], "type": t, "slot": x.get("slot"), "hit": hit,
                         "texts": [fr[i]["text"] for i in ids]})
        marked_pairs = {frozenset(x["fragments"][:2]) for x in d["defects"] + d["twins"] if x["type"].startswith("conflict")}
        # вставленный «конфликтный» пункт может противоречить и другим упоминаниям того же правила — это не ложное
        planted = {i for x in d["defects"] if x["type"] == "conflict" for i in x["fragments"][1:]}
        extra = [k for k in pairs if k not in marked_pairs]
        c["противоречий вне разметки: с вставленным"] += sum(1 for k in extra if k & planted)
        c["противоречий вне разметки: прочие"] += sum(1 for k in extra if not k & planted)
        c["замечаний на «шуме»"] += sum(1 for i in form if fr[i].get("type") in NOISE) + \
            sum(1 for k in pairs if any(fr[i].get("type") in NOISE for i in k))
        c["формулировок вне разметки"] += sum(len(v) for i, v in form.items() if i not in marked)
        c["пунктов"] += len(d["fragments"])
        c["секунд"] += res["seconds"]
    out = ROOT / "data" / "bench" / "gen5_eval.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    for k in sorted(c):
        print(f"{k:40s} {c[k]:.0f}" if isinstance(c[k], float) else f"{k:40s} {c[k]}")


if __name__ == "__main__":
    main()
