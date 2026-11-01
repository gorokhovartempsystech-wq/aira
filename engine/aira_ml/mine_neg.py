"""Трудные отрицательные пары для NLI из реальных ТЗ (dedoc/tz_dataset, MIT): пары похожих пунктов, которые
движок отдал бы на проверку противоречий. В опубликованных ТЗ настоящих противоречий почти нет (на 44 ТЗ
ручной разбор не нашёл ни одного), поэтому метка — «нейтрально» (слабая разметка).

    python -m aira_ml.mine_neg --models dist/models-0.2 --out data/train/nli_real_neg.jsonl

Берём все пары, где текущая NLI видит противоречие (p ≥ 0.5 в обе стороны — их и надо отучить), плюс
случайную долю остальных. Документы делятся на обучение и проверку, чтобы мерить шум на невиданных ТЗ.
Тексты ТЗ содержат ФИО и контакты — файл пар только локально, в репозиторий не кладём.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np

from .engine import K_NLI, Engine, checkable, siblings, softmax
from .realtz import unpack

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=str(ROOT / "dist" / "models-0.2"))
    ap.add_argument("--out", default=str(ROOT / "data" / "train" / "nli_real_neg.jsonl"))
    ap.add_argument("--k", type=int, default=5, help="соседей на пункт (в движке 3 — берём шире, больше трудных пар)")
    ap.add_argument("--easy", type=float, default=0.25, help="доля «лёгких» пар (p < 0.5), которые тоже берём")
    ap.add_argument("--dev-share", type=float, default=0.3)
    ap.add_argument("--threads", type=int, default=6)
    a = ap.parse_args()
    eng = Engine(a.models, a.threads)
    ci = eng.nli_labels.index("contradiction")
    docs = unpack()
    rnd = random.Random(29)
    order = [p.name for p in docs]
    rnd.shuffle(order)
    dev = set(order[:int(len(order) * a.dev_share)])
    out, stat = [], {"train": [0, 0], "dev": [0, 0]}
    for p in docs:
        try:
            frags = [f for f in eng.parse_file(str(p)) if checkable(f)][:400]
        except Exception as e:
            print(p.name, "пропущен:", e)
            continue
        if len(frags) < 2:
            continue
        v = eng.embed(frags)
        sim = v @ v.T
        np.fill_diagonal(sim, -1)
        pairs = set()
        for i in range(len(frags)):
            for j in np.argsort(-sim[i])[:max(K_NLI, a.k)]:
                x, y = sorted((i, int(j)))
                if sim[x, y] >= 0.5 and not siblings(frags[x], frags[y]):
                    pairs.add((x, y))
        pairs = sorted(pairs)
        if not pairs:
            continue
        A = [frags[x]["text"] for x, y in pairs]
        B = [frags[y]["text"] for x, y in pairs]
        pr = softmax(eng.nli.run(A + B, B + A))[:, ci]
        pc = np.minimum(pr[:len(pairs)], pr[len(pairs):])
        split = "dev" if p.name in dev else "train"
        for (x, y), c in zip(pairs, pc):
            hard = c >= 0.5
            if hard or split == "dev" or rnd.random() < a.easy:   # в проверку — все пары, как их увидит движок
                out.append({"a": A[pairs.index((x, y))], "b": B[pairs.index((x, y))], "label": "neutral",
                            "doc": p.name, "split": split, "p_contra_before": round(float(c), 3),
                            "sim": round(float(sim[x, y]), 3)})
                stat[split][0] += 1
                stat[split][1] += int(hard)
        print(f"{p.name}: пунктов {len(frags)}, пар {len(pairs)}, трудных {int((pc >= 0.5).sum())} [{split}]", flush=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    print(json.dumps({"файл": a.out, "документов в проверке": len(dev),
                      "обучение: пар / трудных": stat["train"], "проверка: пар / трудных": stat["dev"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
