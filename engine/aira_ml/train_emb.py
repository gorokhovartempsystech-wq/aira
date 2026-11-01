"""Дообучение эмбеддера движка (rubert-tiny2, CLS + нормировка) на перефразировки — ступень 1 «что задето правкой».

    python -m aira_ml.train_emb --out models/emb-tiny2-aira

Задача ступени 1 — не пропустить места, где упомянут тот же факт другими словами («14 дней» ↔ «две недели»,
«на 11-й день: осталось 3 дня»). Учим контрастивно (InfoNCE, отрицательные — остальные примеры батча):
  • пары «исходный пункт → его упоминание» из синтетики (v3 и Fable: прямо, производное, другими словами,
    косвенно) — с повтором, это главный сигнал;
  • перефразировки ru-HNP (query → pos) и ParaPhraser (точные и близкие).
Трудные отрицательные НЕ используем: противоположное по смыслу на ту же тему (neg в ru-HNP) и ловушки —
это как раз кандидаты, которые ступень 1 должна найти, отсеивает их классификатор пары.
Проверка — полнота top-8 по смыслу на «Возвратах» и пространствах Claude (-c), в обучение они не входят.
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parent.parent
BASE = "cointegrated/rubert-tiny2"
EVAL = [ROOT / "data/spaces/vozvraty.json"] + sorted(Path(p) for p in glob.glob(str(ROOT / "data/spaces/gen/*-c.json")))


def req_pairs(patterns):
    out = []
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            s = json.loads(Path(p).read_text(encoding="utf-8"))
            fr = {f["id"]: f["text"] for f in s["fragments"]}
            for fact in s["facts"]:
                src = fr.get(fact["source"])
                for m in list(fact.get("mentions", {})) + list(fact.get("conflicts", {})):
                    if src and m in fr:
                        out.append((src, fr[m]))
    return out


def para_pairs(n_hnp, n_pp):
    hnp = pd.read_parquet(ROOT / "data/external/ru_hnp/train.parquet")
    rnd = random.Random(3)
    out = []
    for q, pos in zip(hnp["query"], hnp["pos"]):
        out.append((q, rnd.choice(list(pos))))
    rnd.shuffle(out)
    out = out[:n_hnp]
    pp = [json.loads(l) for l in open(ROOT / "data/external/paraphraser/train.jsonl", encoding="utf-8")]
    pp = [(r["text_1"], r["text_2"]) for r in pp if r["class"] in ("0", "1")]
    rnd.shuffle(pp)
    return out + pp[:n_pp]


class Enc(torch.nn.Module):
    def __init__(self, path):
        super().__init__()
        from transformers import AutoModel, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(path)
        self.base = AutoModel.from_pretrained(path)

    def forward(self, texts, dev, max_len=128):
        x = self.tok(texts, truncation=True, max_length=max_len, padding=True, return_tensors="pt").to(dev)
        h = self.base(**x).last_hidden_state[:, 0]
        return torch.nn.functional.normalize(h, dim=-1)

    @torch.inference_mode()
    def encode(self, texts, bs=64):
        dev = next(self.parameters()).device
        return np.concatenate([self(texts[i:i + bs], dev).float().cpu().numpy() for i in range(0, len(texts), bs)])


def recall_at(enc, k=8):
    from . import spaces
    res = {}
    for p in EVAL:
        s, frag, _ = spaces.load(p)
        f = g = 0
        for fact in s["facts"]:
            got = set(spaces.meaning(fact, frag, enc, k))
            f += len(got & set(fact["mentions"]))
            g += len(fact["mentions"])
        res[p.stem] = (f, g)
    tot = sum(x for x, _ in res.values()) / max(1, sum(y for _, y in res.values()))
    return {"все": round(tot, 3), "vozvraty": round(res["vozvraty"][0] / res["vozvraty"][1], 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "models/emb-tiny2-aira"))
    ap.add_argument("--train", nargs="+", default=[str(ROOT / "data/spaces/gen/*-v3.json"), str(ROOT / "data/spaces/gen/*-f.json")])
    ap.add_argument("--hnp", type=int, default=40000)
    ap.add_argument("--pp", type=int, default=6000)
    ap.add_argument("--req-repeat", type=int, default=4)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--scale", type=float, default=20.0)
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    enc = Enc(BASE).to(dev).eval()
    before = recall_at(enc)
    print("до:", before, flush=True)
    req = req_pairs(a.train)
    para = para_pairs(a.hnp, a.pp)
    data = req * a.req_repeat + para
    print(f"пар: требования {len(req)} ×{a.req_repeat}, перефразировки {len(para)}, всего {len(data)}", flush=True)
    opt = torch.optim.AdamW(enc.parameters(), lr=a.lr, weight_decay=0.01)
    steps = a.epochs * (len(data) // a.bs)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / max(1, steps // 10)) * max(0.0, 1 - s / steps))
    scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    t, step = time.time(), 0
    for ep in range(a.epochs):
        random.Random(ep).shuffle(data)
        enc.train()
        for i in range(0, len(data) - a.bs + 1, a.bs):
            batch = data[i:i + a.bs]
            # одинаковые якоря в батче дают ложные отрицательные — оставляем по одному
            seen, b2 = set(), []
            for x, y in batch:
                if x not in seen:
                    seen.add(x)
                    b2.append((x, y))
            with torch.autocast(dev, enabled=dev == "cuda"):
                qa = enc([x for x, _ in b2], dev)
                pa = enc([y for _, y in b2], dev)
                logits = qa @ pa.T * a.scale
                lab = torch.arange(len(b2), device=dev)
                loss = (torch.nn.functional.cross_entropy(logits, lab) + torch.nn.functional.cross_entropy(logits.T, lab)) / 2
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            if step % 200 == 0:
                print(f"шаг {step}/{steps} loss {loss.item():.3f}", flush=True)
    enc.eval()
    after = recall_at(enc)
    print("после:", after, flush=True)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    enc.base.save_pretrained(a.out)
    enc.tok.save_pretrained(a.out)
    info = {"base": BASE, "req_pairs": len(req), "req_repeat": a.req_repeat, "para_pairs": len(para), "epochs": a.epochs,
            "recall8_before": before, "recall8_after": after, "minutes": round((time.time() - t) / 60, 1),
            "eval": [p.name for p in EVAL]}
    (Path(a.out) / "aira_train.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
