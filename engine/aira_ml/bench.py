"""Замеры для десктопа: скорость, память и размер моделей на CPU.

    python -m aira_ml.bench embed deepvk/USER-base --threads 6
    python -m aira_ml.bench cross cointegrated/rubert-tiny2 --threads 6
    python -m aira_ml.bench llm /path/model.gguf --threads 6

Каждый вызов — отдельный процесс, чтобы пиковая память (ru_maxrss) была честной.
Результат дописывается строкой JSON в data/bench/cpu.jsonl.

- embed: скорость кодирования фрагментов требований и качество поиска по смыслу
  (полнота top-8 по фактам стенда «Возвраты» и синтетических пространств);
- cross: скорость классификатора пары «изменение — фрагмент» (энкодер с головой на
  5 классов, веса головы случайные — меряем только скорость): torch fp32, ONNX fp32,
  ONNX int8;
- llm: секунды на одну пару с промптом классификатора из llm.py (llama.cpp, GGUF).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import resource
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "bench" / "cpu.jsonl"
SPACES = [ROOT / "data/spaces/vozvraty.json"] + sorted(Path(p) for p in glob.glob(str(ROOT / "data/spaces/gen/*-c.json")))


def peak_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def dir_mb(model_name):
    from huggingface_hub import snapshot_download
    p = Path(snapshot_download(model_name, allow_patterns=["*.safetensors", "*.json", "*.txt", "*.model"]))
    files = [f for f in p.rglob("*") if f.is_file()]
    weights = [f for f in files if f.suffix == ".safetensors"]
    return sum(f.stat().st_size for f in weights) / 1e6


def save(row):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    row |= {"cpu": platform.processor() or platform.machine(), "time": time.strftime("%Y-%m-%d %H:%M")}
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False))


def texts_and_pairs():
    from . import spaces
    frags, pairs = [], []
    for p in SPACES:
        s, frag, _ = spaces.load(p)
        frags += [f["text"] for f in frag.values()]
        for fact in s["facts"]:
            for i in list(fact["mentions"])[:2]:
                pairs.append((frag[fact["source"]]["text"], fact["change"], frag[i]["text"]))
    return frags, pairs


# --- эмбеддеры --------------------------------------------------------------

def bench_embed(model_name, threads):
    import torch
    torch.set_num_threads(threads)
    from sentence_transformers import SentenceTransformer
    from . import spaces
    size = dir_mb(model_name)
    t = time.time()
    m = SentenceTransformer(model_name, device="cpu")
    load_s = time.time() - t
    pre = "query: " if "e5" in model_name else ""          # e5 обучена с префиксами
    frags, _ = texts_and_pairs()
    frags = [pre + f for f in frags]
    m.encode(frags[:16])                                    # прогрев
    t = time.time()
    m.encode(frags, batch_size=32, normalize_embeddings=True)
    enc_s = time.time() - t

    class Emb:                                              # обёртка под spaces.meaning
        def encode(self, texts):
            return m.encode([pre + x for x in texts], batch_size=32, normalize_embeddings=True)

    found = gold = 0
    for p in SPACES:
        s, frag, _ = spaces.load(p)
        for fact in s["facts"]:
            got = set(spaces.meaning(fact, frag, Emb(), 8))
            found += len(got & set(fact["mentions"]))
            gold += len(fact["mentions"])
    save({"kind": "embed", "model": model_name, "threads": threads, "weights_mb": round(size),
          "load_s": round(load_s, 1), "fragments": len(frags), "frag_per_s": round(len(frags) / enc_s, 1),
          "recall_meaning_top8": round(found / gold, 3), "peak_ram_mb": round(peak_mb())})


# --- классификатор пары ------------------------------------------------------

def pair_text(old, new, cand):
    return f"Было: {old} Стало: {new}", cand


def bench_cross(model_name, threads, n=40, max_len=256):
    import numpy as np
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    torch.set_num_threads(threads)
    size = dir_mb(model_name)
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=5).eval()
    _, pairs = texts_and_pairs()
    pairs = [pair_text(*p) for p in pairs[:n]]
    enc = lambda batch: tok([a for a, _ in batch], [b for _, b in batch], truncation=True, max_length=max_len,  # noqa: E731
                            padding=True, return_tensors="pt")
    with torch.no_grad():
        model(**enc(pairs[:2]))
        t = time.time()
        for p in pairs:
            model(**enc([p]))
        torch_ms = (time.time() - t) / len(pairs) * 1000
        t = time.time()
        for i in range(0, len(pairs), 16):
            model(**enc(pairs[i:i + 16]))
        torch_batch_ms = (time.time() - t) / len(pairs) * 1000

    onnx_dir = ROOT / "data" / "bench" / "onnx" / model_name.replace("/", "__")
    onnx_dir.mkdir(parents=True, exist_ok=True)
    fp32, int8 = onnx_dir / "model.onnx", onnx_dir / "model.int8.onnx"
    if not int8.exists():
        x = enc(pairs[:2])
        names = [k for k in ("input_ids", "attention_mask", "token_type_ids") if k in x]
        torch.onnx.export(model, tuple(x[k] for k in names), str(fp32), input_names=names, output_names=["logits"],
                          dynamic_axes={k: {0: "b", 1: "t"} for k in names} | {"logits": {0: "b"}}, opset_version=17,
                          dynamo=False)
        quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8)
    res = {}
    for label, path in (("onnx_fp32", fp32), ("onnx_int8", int8)):
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        names = [i.name for i in sess.get_inputs()]
        feed = lambda batch: {k: v.numpy() for k, v in enc(batch).items() if k in names}  # noqa: E731
        sess.run(None, feed(pairs[:2]))
        t = time.time()
        for p in pairs:
            sess.run(None, feed([p]))
        res[label + "_ms_per_pair"] = round((time.time() - t) / len(pairs) * 1000, 1)
        res[label + "_mb"] = round(path.stat().st_size / 1e6)
        # согласие int8 с fp32 на тех же парах (доля совпадающих argmax) — грубая проверка, что сжатие не ломает
        if label == "onnx_int8":
            ref = ort.InferenceSession(str(fp32), so, providers=["CPUExecutionProvider"])
            a = np.concatenate([ref.run(None, feed([p]))[0] for p in pairs[:20]]).argmax(1)
            b = np.concatenate([sess.run(None, feed([p]))[0] for p in pairs[:20]]).argmax(1)
            res["int8_argmax_agree"] = round(float((a == b).mean()), 2)
    params = sum(p.numel() for p in model.parameters()) / 1e6
    save({"kind": "cross", "model": model_name, "threads": threads, "params_m": round(params), "weights_mb": round(size),
          "torch_fp32_ms_per_pair": round(torch_ms, 1), "torch_fp32_batch16_ms_per_pair": round(torch_batch_ms, 1),
          **res, "max_len": max_len, "peak_ram_mb": round(peak_mb())})


# --- LLM -----------------------------------------------------------------------

def bench_llm(path, threads, n=6):
    from llama_cpp import Llama
    from .llm import PROMPT, parse
    t = time.time()
    llm = Llama(model_path=path, n_ctx=2048, n_threads=threads, n_gpu_layers=0, verbose=False)
    load_s = time.time() - t
    _, pairs = texts_and_pairs()
    times, prompt_tokens, ok = [], [], 0
    for old, new, cand in pairs[:n]:
        prompt = PROMPT.format(old=old, new=new, cand=cand, kind="фрагмент", doc="", status="действует")
        t = time.time()
        out = llm.create_chat_completion(messages=[{"role": "user", "content": prompt}], max_tokens=80, temperature=0.0)
        times.append(time.time() - t)
        prompt_tokens.append(out["usage"]["prompt_tokens"])
        ok += parse(out["choices"][0]["message"]["content"])[0] is not None
    save({"kind": "llm", "model": Path(path).name, "threads": threads, "file_mb": round(os.path.getsize(path) / 1e6),
          "load_s": round(load_s, 1), "s_per_pair": round(sum(times[1:]) / max(1, len(times) - 1), 2),
          "prompt_tokens_avg": round(sum(prompt_tokens) / len(prompt_tokens)), "parsed_ok": f"{ok}/{len(times)}",
          "peak_ram_mb": round(peak_mb())})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["embed", "cross", "llm"])
    ap.add_argument("model")
    ap.add_argument("--threads", type=int, default=6)
    a = ap.parse_args()
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    {"embed": bench_embed, "cross": bench_cross, "llm": bench_llm}[a.kind](a.model, a.threads)


if __name__ == "__main__":
    main()
