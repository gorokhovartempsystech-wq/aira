"""Своя модель для H2: классификатор пары «изменение — фрагмент» на небольшом энкодере.

    python -m aira_ml.train_cross nli   --base ai-forever/ruBert-base --out models/nli-rubert-base
    python -m aira_ml.train_cross pairs --init models/nli-rubert-base --out models/pair-rubert-base \
        --pairs data/train/pairs_v2.jsonl data/train/pairs_c.jsonl data/train/pairs_v3.jsonl
    python -m aira_ml.train_cross eval  --model models/pair-rubert-base
    python -m aira_ml.train_cross export --model models/pair-rubert-base

Этап 1 (nli): учим энкодер понимать «следует / противоречит / нейтрально» на ru-WANLI
(deepvk/ru-WANLI, Apache-2.0, 100 тыс. пар).
Этап 2 (pairs): дообучаем на наших парах с 4 классами — противоречит / нужно обновить /
не трогать / не связано. Вход: «Было: … Стало: …» + «[тип; статус] фрагмент» — статус
важен: архив и черновик модель должна научиться не трогать.
Разбиение по пространствам (не по парам), иначе одна и та же правка попадёт и в обучение,
и в проверку. После обучения — калибровка температуры на отложенных пространствах,
чтобы уверенность модели можно было показывать как «подсветку сомнений».
eval: тот же стенд, что для GigaChat (ступень 1 + классификатор) на «Возвратах», и
согласие с учителем на отложенных парах.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parent.parent
LABELS = ["contradiction", "update", "keep", "unrelated"]
STATUS_RU = {"active": "действует", "exception": "исключение", "deprecated": "архив",
             "delta": "черновик доработки", "discussion": "обсуждение"}
NLI = {"entailment": 0, "neutral": 1, "contradiction": 2}


def pair_inputs(old, new, frag):
    a = f"Было: {old}\nСтало: {new}"
    b = f"[{frag.get('type', 'фрагмент')}; {STATUS_RU.get(frag.get('status', 'active'), 'действует')}] {frag['text']}"
    return a, b


def device():
    return "cuda" if torch.cuda.is_available() else "cpu"


def train_loop(model, tok, data, labels_count, epochs, lr, bs, max_len, weights=None, log_every=200):
    dev = device()
    model.to(dev).train()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * math.ceil(len(data) / bs)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, s / max(1, int(0.06 * steps))) * max(0.0, (steps - s) / steps))
    scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    lossf = torch.nn.CrossEntropyLoss(weight=torch.tensor(weights, device=dev) if weights else None)
    step = 0
    for ep in range(epochs):
        random.Random(ep).shuffle(data)
        for i in range(0, len(data), bs):
            batch = data[i:i + bs]
            x = tok([a for a, _, _ in batch], [b for _, b, _ in batch], truncation=True, max_length=max_len,
                    padding=True, return_tensors="pt").to(dev)
            y = torch.tensor([l for _, _, l in batch], device=dev)
            with torch.autocast(dev, dtype=torch.float16, enabled=dev == "cuda"):
                loss = lossf(model(**x).logits.float(), y)
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            if step % log_every == 0:
                print(f"  эпоха {ep + 1}, шаг {step}/{steps}, loss {loss.item():.3f}", flush=True)
    model.eval()
    return model


@torch.no_grad()
def logits_of(model, tok, items, max_len=256, bs=64):
    dev = next(model.parameters()).device
    out = []
    for i in range(0, len(items), bs):
        batch = items[i:i + bs]
        x = tok([a for a, b in batch], [b for a, b in batch], truncation=True, max_length=max_len,
                padding=True, return_tensors="pt").to(dev)
        out.append(model(**x).logits.float().cpu())
    return torch.cat(out) if out else torch.zeros(0, 4)


def macro_f1(y, p, n):
    f1s = []
    for c in range(n):
        tp = sum(1 for a, b in zip(y, p) if a == c and b == c)
        fp = sum(1 for a, b in zip(y, p) if a != c and b == c)
        fn = sum(1 for a, b in zip(y, p) if a == c and b != c)
        if tp + fp + fn == 0:
            continue
        f1s.append(2 * tp / (2 * tp + fp + fn))
    return sum(f1s) / len(f1s)


def fit_temperature(logits, y):
    t = torch.ones(1, requires_grad=True)
    opt = torch.optim.LBFGS([t], lr=0.05, max_iter=200)
    yt = torch.tensor(y)

    def closure():
        opt.zero_grad()
        loss = torch.nn.functional.cross_entropy(logits / t.clamp(min=0.05), yt)
        loss.backward()
        return loss
    opt.step(closure)
    return float(t.clamp(min=0.05))


def ece(probs, y, bins=10):
    conf, pred = probs.max(1)
    acc = (pred == torch.tensor(y)).float()
    e = 0.0
    for b in range(bins):
        m = (conf > b / bins) & (conf <= (b + 1) / bins)
        if m.any():
            e += m.float().mean() * abs(acc[m].mean() - conf[m].mean())
    return float(e)


# --- этап 1: NLI ---------------------------------------------------------------

def cmd_nli(a):
    from datasets import load_dataset
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    d = load_dataset("deepvk/ru-WANLI")
    tok = AutoTokenizer.from_pretrained(a.base)
    model = AutoModelForSequenceClassification.from_pretrained(a.base, num_labels=3)
    tr = [(r["premise"], r["hypothesis"], NLI[r["label"]]) for r in d["train"]]
    if a.limit:
        tr = tr[:a.limit]
    t = time.time()
    model = train_loop(model, tok, tr, 3, a.epochs, a.lr, a.bs, 160)
    va = [(r["premise"], r["hypothesis"]) for r in d["validation"]]
    yv = [NLI[r["label"]] for r in d["validation"]]
    pv = logits_of(model, tok, va, 160).argmax(1).tolist()
    acc = sum(int(x == y) for x, y in zip(pv, yv)) / len(yv)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    info = {"stage": "nli", "base": a.base, "train": len(tr), "epochs": a.epochs,
            "val_accuracy": round(acc, 4), "val_macro_f1": round(macro_f1(yv, pv, 3), 4), "minutes": round((time.time() - t) / 60, 1)}
    (Path(a.out) / "aira_train.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))


# --- этап 2: пары ----------------------------------------------------------------

def load_pairs(paths):
    rows = []
    for p in paths:
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if r.get("label") in LABELS:
                rows.append(r)
    seen, out = set(), []
    for r in rows:                           # одинаковые пары из разных прогонов — один раз
        k = (r["old"], r["new"], r["fragment"]["text"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def split_by_space(rows, dev_share=0.15, seed=13):
    spaces = sorted({r["space"] for r in rows})
    random.Random(seed).shuffle(spaces)
    dev = set(spaces[:max(1, int(len(spaces) * dev_share))])
    return [r for r in rows if r["space"] not in dev], [r for r in rows if r["space"] in dev], sorted(dev)


def cmd_pairs(a):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    rows = load_pairs(a.pairs)
    tr, dv, dev_spaces = split_by_space(rows)
    print(f"пар {len(rows)}: обучение {len(tr)}, проверка {len(dv)} ({len(dev_spaces)} пространств)")
    print("классы (обучение):", dict(Counter(r["label"] for r in tr)))
    tok = AutoTokenizer.from_pretrained(a.init)
    model = AutoModelForSequenceClassification.from_pretrained(a.init, num_labels=4, ignore_mismatched_sizes=True)
    model.config.id2label = dict(enumerate(LABELS))
    model.config.label2id = {l: i for i, l in enumerate(LABELS)}
    data = [(*pair_inputs(r["old"], r["new"], r["fragment"]), LABELS.index(r["label"])) for r in tr]
    cnt = Counter(l for *_, l in data)
    weights = [min(5.0, (len(data) / (4 * cnt[c])) ** 0.5) if cnt[c] else 1.0 for c in range(4)]  # мягкие веса редких классов
    t = time.time()
    model = train_loop(model, tok, data, 4, a.epochs, a.lr, a.bs, 256, weights, log_every=50)
    xv = [pair_inputs(r["old"], r["new"], r["fragment"]) for r in dv]
    yv = [LABELS.index(r["label"]) for r in dv]
    lv = logits_of(model, tok, xv)
    temp = fit_temperature(lv, yv)
    pv = lv.argmax(1).tolist()
    probs_raw, probs_cal = lv.softmax(1), (lv / temp).softmax(1)
    flag = lambda i: i in (0, 1)  # noqa: E731
    info = {"stage": "pairs", "init": a.init, "train_pairs": len(tr), "dev_pairs": len(dv), "dev_spaces": dev_spaces,
            "class_weights": [round(w, 2) for w in weights], "epochs": a.epochs,
            "dev_macro_f1_4": round(macro_f1(yv, pv, 4), 4),
            "dev_flag_accuracy": round(sum(flag(p) == flag(y) for p, y in zip(pv, yv)) / len(yv), 4),
            "temperature": round(temp, 3), "ece_raw": round(ece(probs_raw, yv), 4), "ece_calibrated": round(ece(probs_cal, yv), 4),
            "minutes": round((time.time() - t) / 60, 1)}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    (Path(a.out) / "aira_train.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))


# --- оценка на стенде --------------------------------------------------------------

class OwnJudge:
    """Совместим с llm.Judge по интерфейсу judge(old, new, frag) → (label, why)."""

    def __init__(self, path):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path).to(device()).eval()
        info = json.loads((Path(path) / "aira_train.json").read_text(encoding="utf-8"))
        self.temp = info.get("temperature", 1.0)
        self.name = Path(path).name
        self.seconds = 0.0
        self.calls = 0

    def proba(self, old, new, frag):
        t = time.time()
        lg = logits_of(self.model, self.tok, [pair_inputs(old, new, frag)])[0]
        self.seconds += time.time() - t
        self.calls += 1
        return (lg / self.temp).softmax(0).tolist()

    def judge(self, old, new, frag):
        p = self.proba(old, new, frag)
        i = int(np.argmax(p))
        return LABELS[i], f"уверенность {p[i]:.2f}"


def cmd_eval(a):
    from . import spaces
    from .embed import STEmbedder
    from .llm import make_judge
    import os
    emb = STEmbedder()
    own = OwnJudge(a.model)
    os.environ["AIRA_GIGACHAT_MODEL"] = "GigaChat-2-Max"
    giga = make_judge("gigachat")
    out = {}
    for path in a.spaces:
        space, frag, _ = spaces.load(path)
        methods = {"слова": spaces.words, "слова + смысл + статусы": spaces.plus_statuses,
                   "+ своя модель": spaces.with_judge(own), "+ GigaChat-2-Max": spaces.with_judge(giga),
                   "светофор своя 🔴+🟡": spaces.with_disagreement(own, {"red", "yellow"})}
        res = spaces.run(space, frag, emb, methods=methods)
        out[space["id"]] = {m: {k: round(v, 3) if isinstance(v, float) else v for k, v in spaces.summary(rows).items()}
                            for m, rows in res.items()}
    out["своя модель, мс на пару"] = round(own.seconds / max(1, own.calls) * 1000, 1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    (Path(a.model) / "aira_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


# --- экспорт в ONNX int8 -----------------------------------------------------------------

def cmd_export(a):
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(a.model).eval()
    x = tok(["Было: a\nСтало: b"], ["[тип; действует] c"], return_tensors="pt")
    names = [k for k in ("input_ids", "attention_mask", "token_type_ids") if k in x]
    fp32, int8 = Path(a.model) / "model.onnx", Path(a.model) / "model.int8.onnx"
    torch.onnx.export(model, tuple(x[k] for k in names), str(fp32), input_names=names, output_names=["logits"],
                      dynamic_axes={k: {0: "b", 1: "t"} for k in names} | {"logits": {0: "b"}}, opset_version=17, dynamo=False)
    quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8)
    print("ONNX:", fp32.stat().st_size // 10 ** 6, "МБ; int8:", int8.stat().st_size // 10 ** 6, "МБ")


# --- NLI под требования: противоречия из карт v3 -------------------------------------------

def req_nli_rows(paths):
    """Пары (посылка, гипотеза, метка, пространство) из карт генератора v3."""
    import glob as _g
    rows = []
    for p in paths:
        for q in _g.glob(p):
            s = json.loads(Path(q).read_text(encoding="utf-8"))
            fr = {f["id"]: f for f in s["fragments"]}
            filler = [f for f in s["fragments"] if f["status"] == "active" and not any(
                f["id"] in (x["source"], *x["mentions"], *x["traps"], *x.get("conflicts", {})) for x in s["facts"])]
            rnd = random.Random(s["id"])
            for fact in s["facts"]:
                old, new = fr[fact["source"]]["text"], fact["change"]
                for cid in fact.get("conflicts", {}):
                    rows += [(new, fr[cid]["text"], "contradiction", s["id"]), (old, fr[cid]["text"], "neutral", s["id"])]
                for mid, kind in fact["mentions"].items():
                    rows += [(new, fr[mid]["text"], "contradiction", s["id"]),
                             (old, fr[mid]["text"], "entailment" if kind != "косвенно" else "neutral", s["id"])]
                for tid in fact["traps"]:
                    if fr[tid]["status"] in ("active", "exception"):
                        rows.append((new, fr[tid]["text"], "neutral", s["id"]))
                if filler:
                    rows.append((new, rnd.choice(filler)["text"], "neutral", s["id"]))
    both = []
    for a, b, l, sp in rows:                 # противоречие симметрично — учим в обе стороны
        both += [(a, b, l, sp), (b, a, l, sp)]
    return both


def contra_metrics(model, tok, rows):
    xs = [(a, b) for a, b, _, _ in rows]
    p = logits_of(model, tok, xs, 192).softmax(1)[:, NLI["contradiction"]].numpy()
    y = np.array([l == "contradiction" for _, _, l, _ in rows])
    out = {}
    for t in (0.5, 0.85, 0.95):
        pr = p >= t
        tp, fp, fn = int((pr & y).sum()), int((pr & ~y).sum()), int((~pr & y).sum())
        out[str(t)] = {"precision": round(tp / max(1, tp + fp), 3), "recall": round(tp / max(1, tp + fn), 3),
                       "f1": round(2 * tp / max(1, 2 * tp + fp + fn), 3)}
    return out


def cmd_nli_req(a):
    from datasets import load_dataset
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    rows = req_nli_rows(a.spaces)
    spaces = sorted({r[3] for r in rows})
    random.Random(7).shuffle(spaces)
    dev_sp = set(spaces[:max(1, len(spaces) // 6)])
    tr = [r for r in rows if r[3] not in dev_sp]
    dv = [r for r in rows if r[3] in dev_sp]
    print(f"пар {len(rows)} (в обе стороны): обучение {len(tr)}, проверка {len(dv)} ({len(dev_sp)} пространств)")
    print("метки (обучение):", dict(Counter(r[2] for r in tr)))
    tok = AutoTokenizer.from_pretrained(a.init)
    model = AutoModelForSequenceClassification.from_pretrained(a.init).to(device()).eval()
    before = contra_metrics(model, tok, dv)
    wanli = [(r["premise"], r["hypothesis"], NLI[r["label"]]) for r in load_dataset("deepvk/ru-WANLI")["train"]]
    random.Random(1).shuffle(wanli)
    data = [(x, y, NLI[l]) for x, y, l, _ in tr] + wanli[:a.wanli]
    t = time.time()
    model = train_loop(model, tok, data, 3, a.epochs, a.lr, a.bs, 192, log_every=100)
    after = contra_metrics(model, tok, dv)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    info = {"stage": "nli-req", "init": a.init, "base": "ai-forever/ruBert-base", "req_pairs_train": len(tr), "wanli_mix": a.wanli,
            "dev_pairs": len(dv), "dev_spaces": sorted(dev_sp), "contradiction_before": before,
            "contradiction_after": after, "epochs": a.epochs, "minutes": round((time.time() - t) / 60, 1)}
    (Path(a.out) / "aira_train.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: info[k] for k in ("req_pairs_train", "dev_pairs", "contradiction_before", "contradiction_after", "minutes")},
                     ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("nli"); s.add_argument("--base", required=True); s.add_argument("--out", required=True)
    s.add_argument("--epochs", type=int, default=1); s.add_argument("--lr", type=float, default=3e-5)
    s.add_argument("--bs", type=int, default=32); s.add_argument("--limit", type=int, default=0)
    s = sub.add_parser("pairs"); s.add_argument("--init", required=True); s.add_argument("--out", required=True)
    s.add_argument("--pairs", nargs="+", required=True); s.add_argument("--epochs", type=int, default=4)
    s.add_argument("--lr", type=float, default=3e-5); s.add_argument("--bs", type=int, default=16)
    s = sub.add_parser("eval"); s.add_argument("--model", required=True)
    s.add_argument("--spaces", nargs="+", default=[str(ROOT / "data/spaces/vozvraty.json")])
    s = sub.add_parser("export"); s.add_argument("--model", required=True)
    s = sub.add_parser("nli-req"); s.add_argument("--init", required=True); s.add_argument("--out", required=True)
    s.add_argument("--spaces", nargs="+", default=[str(ROOT / "data/spaces/gen/*-v3.json")])
    s.add_argument("--epochs", type=int, default=2); s.add_argument("--lr", type=float, default=2e-5)
    s.add_argument("--bs", type=int, default=32); s.add_argument("--wanli", type=int, default=20000)
    a = ap.parse_args()
    {"nli": cmd_nli, "pairs": cmd_pairs, "eval": cmd_eval, "export": cmd_export, "nli-req": cmd_nli_req}[a.cmd](a)


if __name__ == "__main__":
    main()
