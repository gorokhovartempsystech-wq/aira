"""Оценка гипотезы на пакетах: отбор по похожести против отбора со связями и статусами.

    .venv/bin/python -m aira_ml.evaluate data/packets --split dev
    .venv/bin/python -m aira_ml.evaluate data/packets --embedder tfidf

Метрики (формулы — docs/experiment.md):
- EvidenceRecall@k — доля эталонных требований-оснований в отобранном контексте;
- Recall / Precision противоречий по парам «изменение — требование»;
- FAR — доля корректных изменений, по которым выдано хотя бы одно противоречие.
ДИ разности — бутстреп по пакетам (пакет = семейство документов), не по парам.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from . import select
from .classify import default_classifier
from .embed import STEmbedder, TfidfEmbedder
from .schema import Packet


def load(folder, split=None):
    packets = [Packet.model_validate_json(p.read_text(encoding="utf-8"))
               for p in sorted(Path(folder).glob("*.json"))]
    return [p for p in packets if split in (None, "all", p.split)]


def run_arm(packets, arm, embedder, classifier, k, details=None):
    """Счётчики по каждому пакету — для бутстрепа нужны поштучно."""
    per = []
    sel = select.SELECTORS[arm]
    for p in packets:
        c = dict(ev_hit=0, ev_all=0, tp=0, fp=0, gold=0, correct=0, false_alarm=0)
        for ch in p.changes:
            cands = sel(ch.new_text, ch.requirement_id, p.requirements, embedder, k=k)
            picked = {x.req.id for x in cands}
            c["ev_hit"] += len(set(ch.evidence) & picked)
            c["ev_all"] += len(ch.evidence)
            found = {x.req.id for x in cands
                     if classifier.classify(ch.new_text, x.req.text, x.cos, x.status).relation == "contradiction"}
            gold = {g.requirement_id for g in ch.contradicts}
            if details is not None:
                details.append((arm, ch.id, ch.kind, sorted(gold), sorted(found & gold),
                                sorted(found - gold), sorted(set(ch.evidence) - picked)))
            c["tp"] += len(found & gold)
            c["fp"] += len(found - gold)
            c["gold"] += len(gold)
            if ch.kind == "correct":
                c["correct"] += 1
                c["false_alarm"] += int(bool(found))
        per.append(c)
    return per


def metrics(per):
    s = {k: sum(c[k] for c in per) for k in per[0]} if per else {}
    div = lambda a, b: a / b if b else float("nan")
    return {"EvidenceRecall@k": div(s["ev_hit"], s["ev_all"]),
            "Recall_contr": div(s["tp"], s["gold"]),
            "Precision_contr": div(s["tp"], s["tp"] + s["fp"]),
            "FAR": div(s["false_alarm"], s["correct"]),
            "n_gold": s["gold"], "n_correct": s["correct"]}


def bootstrap_diff(a, b, key, n=1000, seed=13):
    rnd = random.Random(seed)
    idx = range(len(a))
    diffs = []
    for _ in range(n):
        pick = [rnd.choice(idx) for _ in idx]
        ma, mb = metrics([a[i] for i in pick]), metrics([b[i] for i in pick])
        d = mb[key] - ma[key]
        if d == d:  # не NaN
            diffs.append(d)
    diffs.sort()
    if not diffs:
        return float("nan"), float("nan")
    return diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--embedder", choices=["st", "tfidf"], default="st")
    ap.add_argument("--k", type=int, default=select.K)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--details", action="store_true", help="разбор по каждому изменению")
    a = ap.parse_args()

    packets = load(a.folder, a.split)
    emb = STEmbedder() if a.embedder == "st" else TfidfEmbedder()
    clf = default_classifier()
    det = [] if a.details else None
    res = {arm: run_arm(packets, arm, emb, clf, a.k, det) for arm in ("similarity", "structured")}
    table = {arm: metrics(v) for arm, v in res.items()}
    ci = {key: bootstrap_diff(res["similarity"], res["structured"], key)
          for key in ("EvidenceRecall@k", "Recall_contr", "FAR")}
    out = {"packets": len(packets), "changes": sum(len(p.changes) for p in packets),
           "embedder": emb.name, "classifier": clf.name, "k": a.k, "metrics": table,
           "diff_ci95_structured_minus_similarity": ci}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print(f"пакетов {out['packets']}, изменений {out['changes']} · {emb.name} · {clf.name} · k={a.k}")
    print(f"{'метрика':<18}{'similarity':>12}{'structured':>12}   разница, 95% ДИ по пакетам")
    for key in ("EvidenceRecall@k", "Recall_contr", "Precision_contr", "FAR"):
        s, t = table["similarity"][key], table["structured"][key]
        lo, hi = ci.get(key, (float("nan"), float("nan")))
        tail = f"   {t - s:+.2f}  [{lo:+.2f}; {hi:+.2f}]" if key in ci else ""
        print(f"{key:<18}{s:>12.2f}{t:>12.2f}{tail}")
    if det:
        print()
        print("разбор: отбор · изменение · эталон · нашёл верно · ложные · не попало в контекст")
        for arm, cid, kind, gold, hit, fp, miss in det:
            print(f"{arm:<11}{cid:<7}{kind:<14}{','.join(gold) or '—':<18}{','.join(hit) or '—':<18}"
                  f"{','.join(fp) or '—':<26}{','.join(miss) or '—'}")
    print(f"эталонных противоречий {table['similarity']['n_gold']}, корректных изменений "
          f"{table['similarity']['n_correct']} — калибровка, не тест")


if __name__ == "__main__":
    main()
