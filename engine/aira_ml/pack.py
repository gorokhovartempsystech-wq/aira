"""Сборка пакета моделей для десктопа: всё в ONNX int8 + токенизаторы + манифест.

    python -m aira_ml.pack --pair models/pair1-rubert-base --nli models/nli-rubert-base --out dist/models-0.1

В пакете три модели:
- embedder  — cointegrated/rubert-tiny2 (MIT): вектор [CLS] + нормировка, как в sentence-transformers;
- pair      — наш классификатор пары «изменение — фрагмент» (4 класса, температура калибровки);
- nli       — энкодер после ru-WANLI (следует / нейтрально / противоречит) — для противоречий
              внутри документа, где «изменения» нет.
Манифест: версии, размеры, sha256, лицензии, метки классов, температура. Движок (engine.py)
читает только этот пакет и не зависит от PyTorch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

import numpy as np
import torch

EMBEDDER = "cointegrated/rubert-tiny2"
LICENSES = {EMBEDDER: "MIT", "ai-forever/ruBert-base": "Apache-2.0", "deepvk/ru-WANLI": "Apache-2.0 (данные)"}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def quantize(fp32, int8):
    from onnxruntime.quantization import QuantType, quantize_dynamic
    quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8)
    fp32.unlink()


class CLSEncoder(torch.nn.Module):
    def __init__(self, base):
        super().__init__()
        self.base = base

    def forward(self, input_ids, attention_mask, token_type_ids):
        h = self.base(input_ids=input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids).last_hidden_state[:, 0]
        return torch.nn.functional.normalize(h, dim=-1)


def export_embedder(out):
    from transformers import AutoModel, AutoTokenizer
    d = out / "embedder"
    d.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(EMBEDDER)
    model = CLSEncoder(AutoModel.from_pretrained(EMBEDDER)).eval()
    x = tok(["пример требования"], return_tensors="pt")
    names = ["input_ids", "attention_mask", "token_type_ids"]
    torch.onnx.export(model, tuple(x[k] for k in names), str(d / "model.onnx"), input_names=names,
                      output_names=["embedding"], dynamic_axes={k: {0: "b", 1: "t"} for k in names} | {"embedding": {0: "b"}},
                      opset_version=17, dynamo=False)
    quantize(d / "model.onnx", d / "model.int8.onnx")
    tok.save_pretrained(d)
    # проверка: косинус int8 и fp32 на реальных фрагментах
    import onnxruntime as ort
    texts = [f["text"] for f in json.load(open("data/spaces/vozvraty.json", encoding="utf-8"))["fragments"]]
    sess = ort.InferenceSession(str(d / "model.int8.onnx"), providers=["CPUExecutionProvider"])
    xx = tok(texts, padding=True, truncation=True, max_length=256, return_tensors="np")
    q = sess.run(None, {k: xx[k] for k in names})[0]
    with torch.no_grad():
        ref = model(**{k: torch.tensor(xx[k]) for k in names}).numpy()
    cos = float(np.mean(np.sum(q * ref, 1) / np.linalg.norm(q, axis=1)))
    return {"source": EMBEDDER, "license": LICENSES[EMBEDDER], "pooling": "cls+normalize", "dim": int(q.shape[1]),
            "int8_vs_fp32_cosine": round(cos, 4)}


def export_classifier(src, out, name):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(src)
    model = AutoModelForSequenceClassification.from_pretrained(src).eval()
    x = tok(["Было: a\nСтало: b"], ["[тип; действует] c"], return_tensors="pt")
    names = [k for k in ("input_ids", "attention_mask", "token_type_ids") if k in x]
    torch.onnx.export(model, tuple(x[k] for k in names), str(d / "model.onnx"), input_names=names, output_names=["logits"],
                      dynamic_axes={k: {0: "b", 1: "t"} for k in names} | {"logits": {0: "b"}}, opset_version=17, dynamo=False)
    quantize(d / "model.onnx", d / "model.int8.onnx")
    tok.save_pretrained(d)
    info = json.loads((Path(src) / "aira_train.json").read_text(encoding="utf-8"))
    labels = [model.config.id2label[i] for i in range(model.config.num_labels)]
    return {"source": str(src), "base": info.get("base") or info.get("init"), "labels": labels,
            "temperature": info.get("temperature", 1.0), "train": {k: v for k, v in info.items() if k != "dev_spaces"}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True)
    ap.add_argument("--nli", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    man = {"name": "aira-models", "version": out.name.replace("models-", ""), "built": time.strftime("%Y-%m-%d %H:%M"),
           "runtime": "onnxruntime (CPU), int8 dynamic quantization",
           "models": {"embedder": export_embedder(out), "pair": export_classifier(a.pair, out, "pair"),
                      "nli": export_classifier(a.nli, out, "nli")}}
    man["models"]["nli"]["labels"] = ["entailment", "neutral", "contradiction"]   # порядок как в train_cross.NLI
    man["models"]["nli"]["license"] = "Apache-2.0 (ruBert-base) + Apache-2.0 (ru-WANLI)"
    man["models"]["pair"]["license"] = "Apache-2.0 (ruBert-base); данные — синтетические, см. PROVENANCE.md"
    man["files"] = {str(p.relative_to(out)): {"bytes": p.stat().st_size, "sha256": sha256(p)}
                    for p in sorted(out.rglob("*")) if p.is_file()}
    man["total_mb"] = round(sum(v["bytes"] for v in man["files"].values()) / 1e6, 1)
    (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: man[k] for k in ("version", "total_mb")} | {"embedder": man["models"]["embedder"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
