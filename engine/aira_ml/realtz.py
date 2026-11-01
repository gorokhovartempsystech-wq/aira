"""Прогон движка на реальных русских ТЗ из dedoc/tz_dataset (MIT). Только локально: в ТЗ есть ФИО и контакты.

    python -m aira_ml.realtz --models dist/models-0.2

Пишет data/external/dedoc_tz/review.jsonl (все замечания по документам) и печатает сводку.
Разметки «что верно» у ТЗ нет — это проверка на ложные срабатывания и на разбор живых документов.
"""
from __future__ import annotations

import argparse
import json
import time
import zipfile
from collections import Counter
from pathlib import Path

from .engine import Engine

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "external" / "dedoc_tz"


def unpack():
    out = DIR / "docs"
    if not out.exists():
        out.mkdir()
        with zipfile.ZipFile(DIR / "tz_dataset.zip") as z:
            for n in z.namelist():
                if n.startswith("original_documents/") and n.endswith(".docx"):
                    (out / Path(n).name).write_bytes(z.read(n))
    return sorted(out.glob("*.docx"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=str(ROOT / "dist" / "models-0.2"))
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--max-frags", type=int, default=400, help="документы длиннее режем — ревью квадратично по пунктам")
    a = ap.parse_args()
    eng = Engine(a.models, a.threads)
    total, rows = Counter(), []
    with open(DIR / "review.jsonl", "w", encoding="utf-8") as f:
        for p in unpack():
            t0 = time.time()
            try:
                frags = eng.parse_file(str(p))
            except Exception as e:                     # битый docx не должен ронять прогон
                print(f"{p.name}: не разобран — {type(e).__name__}: {e}")
                continue
            cut = len(frags) > a.max_frags
            frags = frags[:a.max_frags]
            res = eng.review(frags)
            c = Counter(f"{i['type']}:{i['light']}" for i in res["issues"])
            st = Counter(fr["status"] for fr in frags)
            title = next((fr["document"] for fr in frags), "")
            row = {"file": p.name, "title": title[:90], "frags": len(frags), "cut": cut, "status": dict(st),
                   "issues": dict(c), "sec": round(time.time() - t0, 1)}
            rows.append(row)
            total.update(c)
            total["docs"] += 1
            total["frags"] += len(frags)
            f.write(json.dumps({**row, "all": res["issues"], "questions": res.get("questions", [])}, ensure_ascii=False) + "\n")
            print(json.dumps(row, ensure_ascii=False), flush=True)
    print("ИТОГО", json.dumps(dict(total), ensure_ascii=False))


if __name__ == "__main__":
    main()
