"""Движок на «Возвратах» (набор для настройки): влияние правки по всем фактам карты, как в стенде.

    python -m aira_ml.engine_eval dist/models-0.2 dist/models-0.4

Печатает полноту и точность красных и красных+жёлтых, число мест и ловушек, и какие упоминания пропущены.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import Engine

ROOT = Path(__file__).resolve().parent.parent


def evaluate(models, space=ROOT / "data/spaces/vozvraty.json"):
    e = Engine(models, threads=4)
    s = json.loads(Path(space).read_text(encoding="utf-8"))
    frags = [{k: f[k] for k in ("id", "text", "type", "status", "document")} for f in s["fragments"]]
    by = {f["id"]: f for f in frags}
    found = gold = ret = traps = red_found = red_ret = 0
    missed = []
    for fact in s["facts"]:
        r = e.impact(frags, fact["change"], fact["source"])
        got = {x["fragment_id"] for x in r["issues"]}
        red = {x["fragment_id"] for x in r["issues"] if x["light"] == "red"}
        m = set(fact["mentions"])
        found += len(got & m); gold += len(m); ret += len(got); traps += len(got & set(fact["traps"]))
        red_found += len(red & m); red_ret += len(red)
        missed += [f"{fact['id']}: {by[i]['text'][:80]} [{fact['mentions'][i]}]" for i in sorted(m - got)]
    return {"models": Path(models).name, "red_recall": round(red_found / gold, 3), "red_precision": round(red_found / max(1, red_ret), 3),
            "red_places": red_ret, "all_recall": round(found / gold, 3), "all_precision": round(found / max(1, ret), 3),
            "all_places": ret, "traps": traps, "missed": missed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    for m in ap.parse_args().models:
        print(json.dumps(evaluate(m), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
