"""Адаптер веток декомпозиции → обучающие пары, проверенные учителем.

    python -m aira_ml.branches data/spaces/gen/*-f.json            # формат промта для Claude Fable (поле branches)
    python -m aira_ml.branches data/spaces/gen/*-v4.json --out data/train/pairs_branches_v4.jsonl

Ветка: верхнее требование (high), его правка (change), детальные этой ветки, которые правка
задевает (affected) и не задевает (not_affected), и трудные отрицательные — детальные
тематически близкой соседней ветки (hard_negatives).

Из ветки получаются пары двух видов, обе — через независимого учителя, в обучение идут только
пары, где учитель согласен с картой генератора (так в v2 не было: пары трассировки шли без
проверки, и модель научилась метить слишком широко):

1. change — «Было: верхнее / Стало: правка» × фрагмент. Учитель — тот же классификатор пары,
   что для v2/v3 (llm.Judge, GigaChat-2-Max). Карта: affected → затронуто; not_affected и
   hard_negatives → нет. Метка в обучении — метка учителя (update / contradiction / keep / unrelated).
2. trace — «Стало: верхнее (требование будет изменено)» × фрагмент — постановка D12, где текста
   правки нет. Учитель — вопрос «зависит ли детальное от верхнего» (coverage.PROMPT_DEP_RU).
   Карта: все детальные ветки → зависит (update); hard_negatives → не зависит (unrelated).

Пространства v4 (ночная генерация 26.10) поля branches не имеют — ветки восстанавливаются из
facts: source = верхнее, mentions = affected, traps «та же ветка…» = not_affected,
traps «другая ветка» = hard_negatives.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "train" / "pairs_branches.jsonl"
GENERIC = " (требование будет изменено)"
FLAG = {"contradiction", "update"}


def branches_of(space):
    """Ветки пространства в едином виде. Ошибки структуры — в список errors."""
    frag = {f["id"]: f for f in space["fragments"]}
    out, errors = [], []
    if space.get("branches"):
        raw = [{"id": b.get("id", f"B{i}"), "high": b["high"], "change": b["change"],
                "affected": list(b.get("affected", [])), "not_affected": list(b.get("not_affected", [])),
                "hard_negatives": list(b.get("hard_negatives", []))} for i, b in enumerate(space["branches"], 1)]
    elif str(space.get("source", "")).endswith("decomposition"):          # v4: восстанавливаем из facts
        raw = []
        for f in space["facts"]:
            raw.append({"id": f["id"], "high": f["source"], "change": f["change"], "affected": list(f["mentions"]),
                        "not_affected": [k for k, why in f["traps"].items() if why.startswith("та же ветка")],
                        "hard_negatives": [k for k, why in f["traps"].items() if why.startswith("другая ветка")]})
    else:
        return [], []
    for b in raw:
        ids = [b["high"], *b["affected"], *b["not_affected"], *b["hard_negatives"]]
        missing = [i for i in ids if i not in frag]
        if missing:
            errors.append(f"{b['id']}: нет фрагментов {missing}")
            continue
        if len(set(ids)) != len(ids):
            errors.append(f"{b['id']}: фрагмент в двух группах сразу")
            continue
        if not b["affected"]:
            errors.append(f"{b['id']}: нет affected")
            continue
        out.append(b)
    return out, errors


def candidate_pairs(space, b):
    """Пары ветки с картой генератора: (вид, old, new, fragment, ожидание «затронуто/зависит»)."""
    frag = {f["id"]: f for f in space["fragments"]}
    old = frag[b["high"]]["text"]
    rows = []
    for k in b["affected"]:
        rows.append(("change", old, b["change"], frag[k], True))
    for k in b["not_affected"] + b["hard_negatives"]:
        rows.append(("change", old, b["change"], frag[k], False))
    for k in b["affected"] + b["not_affected"]:
        rows.append(("trace", old, old + GENERIC, frag[k], True))
    for k in b["hard_negatives"]:
        rows.append(("trace", old, old + GENERIC, frag[k], False))
    return rows


def label(kind, judge, dep, old, new, fr):
    """Метка учителя и «затронуто ли» по его мнению."""
    if kind == "change":
        lab, _ = judge.judge(old, new, fr)
        return lab, lab in FLAG
    yes = dep(old, fr["text"])
    return ("update" if yes else "unrelated"), yes


def run(paths, out, judge=None, dep=None):
    if judge is None or dep is None:
        from .coverage import DepJudge
        from .llm import make_judge
        os.environ.setdefault("AIRA_GIGACHAT_MODEL", "GigaChat-2-Max")
        judge = judge or make_judge("gigachat")
        dep = dep or DepJudge("gigachat", "ru")
    kept, stats = [], Counter()
    by_space = {}
    for p in paths:
        space = json.loads(Path(p).read_text(encoding="utf-8"))
        bs, errors = branches_of(space)
        for e in errors:
            print(f"  {space['id']}: {e}")
        for b in bs:
            for kind, old, new, fr, expect in candidate_pairs(space, b):
                lab, flagged = label(kind, judge, dep, old, new, fr)
                agree = flagged == expect
                stats[(kind, "pairs")] += 1
                stats[(kind, "agree")] += agree
                stats[(kind, "exp_yes_said_no" if expect and not flagged else "exp_no_said_yes" if flagged and not expect else "ok")] += 1
                by_space.setdefault(space["id"], Counter()).update({"pairs": 1, "agree": int(agree)})
                if agree:
                    kept.append({"old": old, "new": new, "fragment": fr, "label": lab, "space": space["id"],
                                 "variant": kind})
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
    return kept, stats, by_space


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    paths = [q for p in a.paths for q in sorted(glob.glob(p))]
    kept, stats, by_space = run(paths, a.out)
    print("| пространство | пар | согласие учителя |\n|---|---|---|")
    for sp, c in sorted(by_space.items()):
        print(f"| {sp} | {c['pairs']} | {c['agree'] / max(1, c['pairs']):.0%} |")
    for kind in ("change", "trace"):
        n = stats[(kind, "pairs")]
        if n:
            print(f"{kind}: пар {n}, согласие {stats[(kind, 'agree')] / n:.0%} "
                  f"(карта «да», учитель «нет»: {stats[(kind, 'exp_yes_said_no')]}; карта «нет», учитель «да»: {stats[(kind, 'exp_no_said_yes')]})")
    print(f"в обучение: {len(kept)} пар {dict(Counter(r['label'] for r in kept))} → {a.out}")


if __name__ == "__main__":
    main()
