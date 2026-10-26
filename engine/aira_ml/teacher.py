"""Разметка учителем и сборка обучающих пар.

    .venv/bin/python -m aira_ml.teacher data/spaces/gen/*.json --review review.md

Для каждого факта каждого сгенерированного пространства берём кандидатов ступени 1
(«+ статусы») плюс все размеченные генератором фрагменты (упоминания, ловушки) —
так в обучение попадают и положительные примеры, и трудные отрицательные.
Учитель (GigaChat-2-Max) независимо ставит метку каждой паре. Сравниваем с картой
генератора: согласие — сигнал качества; в обучение идут только пары, где они согласны.
Расхождения выписываются для ручной проверки.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from .embed import STEmbedder
from .llm import FLAG, GigaChatBackend, Judge, load_env
from .spaces import load as load_space, plus_statuses

ROOT = Path(__file__).resolve().parent.parent
TRAIN = ROOT / "data" / "train" / "pairs.jsonl"


def gold_of(fact, fid):
    if fid in fact["mentions"] or fid in fact.get("conflicts", {}):
        return "flag"
    if fid in fact.get("soft", {}):
        return "soft"
    if fid in fact.get("traps", {}):
        return "trap"
    return "other"


def run(paths, judge, emb):
    rows = []
    for p in paths:
        space, frag, errors = load_space(p)
        if errors:
            print(f"{p.name}: пропущен — {len(errors)} ошибок структуры")
            continue
        for fact in space["facts"]:
            cands = list(dict.fromkeys(plus_statuses(fact, frag, emb)
                                       + list(fact["mentions"]) + list(fact.get("conflicts", {}))
                                       + list(fact.get("traps", {}))))
            old, new = frag[fact["source"]]["text"], fact["change"]
            for fid in cands:
                if fid == fact["source"]:
                    continue
                label, why = judge.judge(old, new, frag[fid])
                gold = gold_of(fact, fid)
                rows.append({"space": space["id"], "fact": fact["id"], "fact_name": fact.get("name", ""),
                             "old": old, "new": new, "fragment_id": fid, "fragment": frag[fid],
                             "gold": gold, "teacher": label, "why": why,
                             "agree": None if gold == "soft" else (gold == "flag") == (label in FLAG)})
    return rows


def report(rows):
    by = Counter()
    for r in rows:
        by[(r["space"], r["agree"])] += 1
    spaces = sorted({r["space"] for r in rows})
    lines = ["| пространство | пар | согласие учителя с генератором | расхождений |", "|---|---|---|---|"]
    for s in spaces:
        a, d = by[(s, True)], by[(s, False)]
        lines.append(f"| {s} | {a + d + by[(s, None)]} | {a / (a + d):.0%} | {d} |" if a + d else f"| {s} | 0 | — | 0 |")
    a = sum(v for (s, ag), v in by.items() if ag is True)
    d = sum(v for (s, ag), v in by.items() if ag is False)
    lines.append(f"| **всего** | {len(rows)} | **{a / (a + d):.0%}** | {d} |")
    kinds = Counter((r["gold"], "flag" if r["teacher"] in FLAG else "нет") for r in rows if r["agree"] is False)
    lines += ["", "Где расходятся (генератор → учитель): " +
              ", ".join(f"{g} → {t}: {n}" for (g, t), n in kinds.most_common())]
    return "\n".join(lines)


def review_md(rows, limit=30):
    out = ["## Расхождения учителя и генератора — посмотреть глазами", "",
           "Генератор: flag — «нужно править», trap — ловушка, other — не размечен.",
           "Учитель: противоречит / нужно обновить / не трогать / не связано.", ""]
    for r in [r for r in rows if r["agree"] is False][:limit]:
        f = r["fragment"]
        out += [f"**{r['space']} · {r['fact']} {r['fact_name']}** — генератор: `{r['gold']}`, учитель: `{r['teacher']}`",
                f"- было: {r['old']}", f"- стало: {r['new']}",
                f"- фрагмент {r['fragment_id']} ({f.get('type', '')}, {f.get('status', '')}): {f['text']}",
                f"- учитель: {r['why']}", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--review", default=None)
    a = ap.parse_args()
    load_env()
    os.environ["AIRA_GIGACHAT_MODEL"] = os.getenv("AIRA_TEACHER_MODEL", "GigaChat-2-Max")
    judge = Judge(GigaChatBackend())
    rows = run([Path(p) for p in a.paths], judge, STEmbedder())
    TRAIN.parent.mkdir(parents=True, exist_ok=True)
    with open(TRAIN, "w", encoding="utf-8") as fh:
        for r in rows:
            if r["agree"]:
                fh.write(json.dumps({"old": r["old"], "new": r["new"], "fragment": r["fragment"],
                                     "label": r["teacher"], "space": r["space"]}, ensure_ascii=False) + "\n")
    rep = report(rows)
    print(rep)
    print(f"в обучение: {sum(1 for r in rows if r['agree'])} пар → {TRAIN.relative_to(ROOT)};"
          f" новых вызовов учителя {judge.calls}")
    if a.review:
        Path(a.review).write_text(rep + "\n\n" + review_md(rows), encoding="utf-8")


if __name__ == "__main__":
    main()
