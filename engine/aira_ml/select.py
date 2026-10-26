"""Отбор контекста для проверки изменения — то, что меняется в эксперименте.

Гипотеза (карточка 11.09 + разбор 29.09): при одинаковом классификаторе
и одинаковом бюджете контекста отбор с учётом связей и статусов находит
больше противоречий, чем отбор только по похожести, без роста ложных тревог.

Два варианта с одним интерфейсом:
- similarity — top-k по косинусу, статусы классификатору не показываем;
- structured — те же косинусы плюс явные связи и раздел; отменённые версии
  и обсуждения не берём; статус передаём классификатору.
Бюджет одинаковый: не больше k кандидатов и max_chars символов текста.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

K = 8
MAX_CHARS = 6000          # ≈ 2000 токенов русского текста
LINK_BONUS = 0.15
SECTION_BONUS = 0.05
_ID = re.compile(r"\b[A-ZА-Я]{2,6}-\d{1,4}\b")


@dataclass
class Candidate:
    req: object                 # schema.Requirement
    score: float
    cos: float
    status: str | None          # None — классификатор статус не видит
    reasons: list[str] = field(default_factory=list)


def _cosines(embedder, query, reqs):
    vecs = embedder.encode([query] + [r.text for r in reqs])
    return vecs[1:] @ vecs[0]


def _budget(cands, k, max_chars):
    out, used = [], 0
    for c in cands:
        if len(out) >= k or used + len(c.req.text) > max_chars:
            break
        out.append(c)
        used += len(c.req.text)
    return out


def similarity(query, changed_id, reqs, embedder, k=K, max_chars=MAX_CHARS):
    pool = [r for r in reqs if r.id != changed_id]
    if not pool:
        return []
    cos = _cosines(embedder, query, pool)
    order = np.argsort(-cos)
    return _budget([Candidate(pool[i], float(cos[i]), float(cos[i]), None, ["похожесть"]) for i in order],
                   k, max_chars)


def structured(query, changed_id, reqs, embedder, k=K, max_chars=MAX_CHARS):
    changed = next((r for r in reqs if r.id == changed_id), None)
    # из нескольких версий одного требования берём последнюю не отменённую
    latest = {}
    for r in reqs:
        if r.id == changed_id or r.status in ("deprecated", "discussion"):
            continue
        if r.id not in latest or r.version > latest[r.id].version:
            latest[r.id] = r
    pool = list(latest.values())
    if not pool:
        return []
    cos = _cosines(embedder, query, pool)
    linked = set(changed.links) if changed else set()
    linked |= set(_ID.findall(query))
    section = changed.section if changed else ""
    cands = []
    for r, c in zip(pool, cos):
        score, why = float(c), ["похожесть"]
        if r.id in linked or changed_id in r.links or changed_id in _ID.findall(r.text):
            score += LINK_BONUS
            why.append("явная связь")
        if section and r.section == section:
            score += SECTION_BONUS
            why.append("тот же раздел")
        cands.append(Candidate(r, score, float(c), r.status, why))
    cands.sort(key=lambda x: -x.score)
    return _budget(cands, k, max_chars)


SELECTORS = {"similarity": similarity, "structured": structured}
