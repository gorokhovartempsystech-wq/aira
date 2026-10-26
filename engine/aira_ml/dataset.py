"""Датасет: проверка пакетов, статистика, выгрузка для разметчиков, каппа.

    .venv/bin/python -m aira_ml.dataset check  data/packets
    .venv/bin/python -m aira_ml.dataset stats  data/packets
    .venv/bin/python -m aira_ml.dataset export data/packets разметка/артём.csv --sample 0.3
    .venv/bin/python -m aira_ml.dataset kappa  data/packets разметка/артём.csv [разметка/второй.csv]

Выгрузка не показывает эталон: разметчик видит изменение и кандидатов и решает сам.
Кандидаты — эталон, основания и то, что поднимают оба способа отбора, перемешанные.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path

from . import select
from .classify import quantities
from .embed import TfidfEmbedder
from .schema import Packet

YES = {"да", "противоречие", "1", "yes", "y", "+"}
NO = {"нет", "0", "no", "n", "-"}


def load_all(folder):
    out, errors = [], []
    for f in sorted(Path(folder).glob("*.json")):
        try:
            out.append((f.name, Packet.model_validate_json(f.read_text(encoding="utf-8"))))
        except Exception as e:  # pydantic или JSON
            errors.append(f"{f.name}: не читается — {str(e).splitlines()[0]}")
    return out, errors


def is_numeric(change, quote):
    a = {u for _, u, *_ in quantities(change.new_text)}
    b = {u for _, u, *_ in quantities(quote)}
    return bool(a & b)


def check(packets):
    errs, warns = [], []
    families = Counter(p.family for _, p in packets)
    for fam, n in families.items():
        if n > 1:
            errs.append(f"семейство «{fam}» встречается в {n} пакетах — разбиение по семействам сломается")
    for name, p in packets:
        by_id = {}
        for r in p.requirements:
            if (r.id, r.version) in by_id:
                errs.append(f"{name}: повтор {r.id} v{r.version}")
            by_id[(r.id, r.version)] = r
        ids = {r.id for r in p.requirements}
        active = {r.id: r for r in p.requirements if r.status == "active"}
        st = Counter(r.status for r in p.requirements)
        for need in ("deprecated", "exception", "discussion"):
            if not st[need]:
                warns.append(f"{name}: нет ни одного требования со статусом {need}")
        for r in p.requirements:
            for l in r.links:
                if l not in ids:
                    errs.append(f"{name}: {r.id} ссылается на несуществующий {l}")
        for ch in p.changes:
            tag = f"{name}/{ch.id}"
            base = active.get(ch.requirement_id)
            if not base:
                errs.append(f"{tag}: меняется не действующее требование {ch.requirement_id}")
            elif ch.old_text and ch.old_text != base.text:
                errs.append(f"{tag}: old_text не совпадает с текстом {ch.requirement_id}")
            if ch.new_text == ch.old_text:
                errs.append(f"{tag}: изменение ничего не меняет")
            if ch.kind == "correct" and ch.contradicts:
                errs.append(f"{tag}: корректное изменение с эталонными противоречиями")
            if ch.kind == "contradicting" and not ch.contradicts:
                errs.append(f"{tag}: противоречащее изменение без эталона")
            for g in ch.contradicts:
                r = active.get(g.requirement_id)
                if not r:
                    errs.append(f"{tag}: эталон {g.requirement_id} не существует или не действует")
                elif g.quote not in r.text:
                    errs.append(f"{tag}: цитата не найдена дословно в {g.requirement_id}: «{g.quote[:50]}…»")
                if g.requirement_id == ch.requirement_id:
                    errs.append(f"{tag}: требование противоречит само себе")
            for e in ch.evidence:
                if e not in ids:
                    errs.append(f"{tag}: основание {e} не существует")
            missing = {g.requirement_id for g in ch.contradicts} - set(ch.evidence)
            if missing:
                warns.append(f"{tag}: эталон {', '.join(sorted(missing))} не входит в evidence")
    return errs, warns


def stats(packets):
    s = Counter()
    for _, p in packets:
        s[f"семейств_{p.split}"] += 1
        s["требований"] += len(p.requirements)
        for ch in p.changes:
            s[f"изменений_{p.split}"] += 1
            if ch.kind == "correct":
                s[f"корректных_{p.split}"] += 1
            for g in ch.contradicts:
                s[f"противоречий_{p.split}"] += 1
                s["числовых" if is_numeric(ch, g.quote) else "смысловых"] += 1
    return s


def candidates(p, ch, emb, k=6):
    pool = {g.requirement_id for g in ch.contradicts} | set(ch.evidence)
    for arm in select.SELECTORS.values():
        pool |= {c.req.id for c in arm(ch.new_text, ch.requirement_id, p.requirements, emb, k=k)}
    pool.discard(ch.requirement_id)
    return sorted(pool)


def export(packets, out, sample, seed):
    rnd = random.Random(seed)
    emb = TfidfEmbedder()
    rows = []
    for _, p in packets:
        latest = {}
        for r in p.requirements:
            if r.id not in latest or r.version > latest[r.id].version:
                latest[r.id] = r
        for ch in p.changes:
            if rnd.random() > sample:
                continue
            for rid in candidates(p, ch, emb):
                r = latest[rid]
                rows.append({"pair_id": f"{ch.id}|{rid}", "пакет": p.id, "изменение": ch.id,
                             "было": ch.old_text or "", "стало": ch.new_text,
                             "другое требование": rid, "статус": r.status, "документ": r.document,
                             "текст": r.text, "противоречие (да/нет)": "", "комментарий": ""})
    rnd.shuffle(rows)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:   # BOM — чтобы Excel открыл кириллицу
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return len(rows), len({r["изменение"] for r in rows})


def read_labels(path):
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            v = (row.get("противоречие (да/нет)") or "").strip().lower()
            if v in YES:
                out[row["pair_id"]] = 1
            elif v in NO:
                out[row["pair_id"]] = 0
    return out


def gold_labels(packets):
    g = {}
    for _, p in packets:
        for ch in p.changes:
            for x in ch.contradicts:
                g[f"{ch.id}|{x.requirement_id}"] = 1
    return g


def cohen_kappa(a, b, keys):
    n = len(keys)
    if not n:
        return float("nan")
    po = sum(a.get(k, 0) == b.get(k, 0) for k in keys) / n
    pa, pb = sum(a.get(k, 0) for k in keys) / n, sum(b.get(k, 0) for k in keys) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("check", "stats"):
        sub.add_parser(c).add_argument("folder")
    e = sub.add_parser("export")
    e.add_argument("folder"); e.add_argument("out")
    e.add_argument("--sample", type=float, default=1.0); e.add_argument("--seed", type=int, default=7)
    kp = sub.add_parser("kappa")
    kp.add_argument("folder"); kp.add_argument("first"); kp.add_argument("second", nargs="?")
    a = ap.parse_args()

    packets, load_errors = load_all(a.folder)
    if a.cmd == "check":
        errs, warns = check(packets)
        errs = load_errors + errs
        for x in errs:
            print("ОШИБКА ", x)
        for x in warns:
            print("внимание", x)
        print(f"пакетов {len(packets)}, ошибок {len(errs)}, предупреждений {len(warns)}")
        sys.exit(1 if errs else 0)
    if a.cmd == "stats":
        s = stats(packets)
        for split in ("dev", "test"):
            print(f"{split:<5} семейств {s[f'семейств_{split}']:>3} · изменений {s[f'изменений_{split}']:>4}"
                  f" · эталонных противоречий {s[f'противоречий_{split}']:>4}"
                  f" · корректных изменений {s[f'корректных_{split}']:>3}")
        tot = s["числовых"] + s["смысловых"]
        print(f"требований {s['требований']} · противоречий с числами {s['числовых']}"
              f", смысловых {s['смысловых']} ({s['смысловых'] / tot:.0%})" if tot else "")
        return
    if a.cmd == "export":
        n, m = export(packets, a.out, a.sample, a.seed)
        print(f"выгружено {n} пар по {m} изменениям → {a.out}")
        return
    if a.cmd == "kappa":
        first = read_labels(a.first)
        gold = gold_labels(packets)
        keys = sorted(first)
        print(f"размечено пар: {len(keys)}")
        print(f"каппа «{Path(a.first).stem}» против эталона: {cohen_kappa(first, gold, keys):.2f}")
        if a.second:
            second = read_labels(a.second)
            both = sorted(set(first) & set(second))
            print(f"каппа между разметчиками на {len(both)} общих парах: {cohen_kappa(first, second, both):.2f}")
            diff = [k for k in both if first[k] != second[k]]
            for k in diff[:30]:
                print("расхождение:", k)


if __name__ == "__main__":
    main()
