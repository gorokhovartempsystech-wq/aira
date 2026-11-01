"""Внешняя проверка NLI-моделей на русских наборах с разметкой людей: XNLI-ru (test), TERRa и RCB (validation).

    python -m aira_ml.nli_eval models/nli-rubert-base models/nli3-rubert-base

Наши модели: 0 — следование, 1 — нейтрально, 2 — противоречие. TERRa бинарный (следует / не следует),
поэтому там «не следует» = нейтрально или противоречие. Считается на CPU, чтобы не мешать обучению на GPU.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "data" / "external"
NAMES = ["entailment", "neutral", "contradiction"]


def load_sets():
    x = pd.read_parquet(EXT / "xnli_ru" / "ru" / "test-00000-of-00001.parquet")
    terra = pd.read_parquet(EXT / "rsg" / "terra" / "validation" / "0000.parquet")
    rcb = pd.read_parquet(EXT / "rsg" / "rcb" / "validation" / "0000.parquet")
    # метки: XNLI 0/1/2 = entailment/neutral/contradiction; TERRa 0/1 = entailment/not_entailment;
    # RCB 0/1/2 = entailment/contradiction/neutral (порядок RussianSuperGLUE)
    return {
        "XNLI-ru test": (list(x.premise), list(x.hypothesis), [NAMES[i] for i in x.label]),
        "TERRa val": (list(terra.premise), list(terra.hypothesis), ["entailment" if i == 0 else "not" for i in terra.label]),
        "RCB val": (list(rcb.premise), list(rcb.hypothesis), [["entailment", "contradiction", "neutral"][i] for i in rcb.label]),
    }


@torch.inference_mode()
def predict(model, tok, a, b, bs=32):
    out = []
    for i in range(0, len(a), bs):
        enc = tok(a[i:i + bs], b[i:i + bs], truncation=True, max_length=192, padding=True, return_tensors="pt")
        out += model(**enc).logits.argmax(-1).tolist()
    return [NAMES[i] for i in out]


def scores(gold, pred, binary=False):
    if binary:
        pred = ["entailment" if p == "entailment" else "not" for p in pred]
    acc = sum(g == p for g, p in zip(gold, pred)) / len(gold)
    res = {"n": len(gold), "accuracy": round(acc, 3)}
    if not binary:
        tp = sum(g == p == "contradiction" for g, p in zip(gold, pred))
        np_, ng = pred.count("contradiction"), gold.count("contradiction")
        res |= {"contra_P": round(tp / max(1, np_), 3), "contra_R": round(tp / max(1, ng), 3)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--threads", type=int, default=6)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    sets = load_sets()
    for m in a.models:
        tok = AutoTokenizer.from_pretrained(m)
        model = AutoModelForSequenceClassification.from_pretrained(m).eval()
        for name, (p, h, gold) in sets.items():
            t0 = time.time()
            pred = predict(model, tok, p, h)
            r = scores(gold, pred, binary=name.startswith("TERRa"))
            print(json.dumps({"model": Path(m).name, "set": name, **r, "sec": round(time.time() - t0)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
