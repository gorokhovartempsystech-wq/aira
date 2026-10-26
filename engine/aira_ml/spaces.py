"""Стенд «пространство + карта фактов»: меняем факт в одном месте — кто найдёт остальные.

    .venv/bin/python -m aira_ml.spaces data/spaces/vozvraty.json --md
    .venv/bin/python -m aira_ml.spaces data/spaces/vozvraty.json --drop-links 0.5

Пространство — фрагменты документов модуля (правила, критерии приёмки, шаги
сценариев, требования, поля API, тексты для клиента, глоссарий, архив,
доработка, обсуждение) со статусами и связями. Карта фактов — для каждого
факта: где он упомянут («нужно обновить»), где стоит проверить, и ловушки.

Способы поиска выстроены лесенкой — каждая ступень добавляет одно:
слова → смысл → слова + смысл → + статусы → + связи. Так видно вклад каждой
части (абляция). Связи есть не всегда, поэтому отдельно проверяем, что будет,
если часть связей удалить (--drop-links).
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

import numpy as np

from .embed import STEmbedder, TfidfEmbedder

K = 8
SKIP_STATUSES = {"deprecated", "delta", "discussion"}
LINK1_BONUS = 0.20     # прямая связь с изменённым фрагментом
LINK2_BONUS = 0.08     # через один промежуточный фрагмент
_ID = re.compile(r"\b[A-ZА-Я]{2,4}-\d{2}(?:-[A-Z]\d)?\b")


def load(path):
    space = json.loads(Path(path).read_text(encoding="utf-8"))
    frag = {f["id"]: f for f in space["fragments"]}
    errors = []
    for f in space["fragments"]:
        errors += [f"{f['id']}: связь на несуществующий {l}" for l in f.get("links", []) if l not in frag]
    for fact in space["facts"]:
        groups = [fact["source"]], list(fact["mentions"]), list(fact["soft"]), list(fact["traps"])
        for g in groups:
            errors += [f"{fact['id']}: нет фрагмента {i}" for i in g if i not in frag]
        flat = [i for g in groups for i in g]
        if len(flat) != len(set(flat)):
            errors.append(f"{fact['id']}: фрагмент в двух группах сразу")
    return space, frag, errors


def neighbours(frag):
    """Связи без направления: явные links + упоминание ID в тексте."""
    nb = {i: set() for i in frag}
    for i, f in frag.items():
        for j in set(f.get("links", [])) | set(_ID.findall(f["text"])):
            if j in frag and j != i:
                nb[i].add(j)
                nb[j].add(i)
    return nb


def drop_links(frag, share, seed=7):
    """Копия пространства, где удалена доля связей — проверка «связи есть не всегда»."""
    rnd = random.Random(seed)
    out = {}
    for i, f in frag.items():
        g = dict(f)
        g["links"] = [l for l in f.get("links", []) if rnd.random() >= share]
        out[i] = g
    return out


# --- способы поиска --------------------------------------------------------

def words(fact, frag, embedder=None, k=None):
    """Как поиск в Confluence: всё, где встречается любой из запросов аналитика."""
    terms = [t.lower() for t in fact["search_terms"]]
    return [i for i, f in frag.items()
            if i != fact["source"] and any(t in f["text"].lower() for t in terms)]


def _topk(fact, frag, embedder, k, statuses=False, links=False):
    pool = [i for i in frag if i != fact["source"]
            and not (statuses and frag[i]["status"] in SKIP_STATUSES)]
    vecs = embedder.encode([frag[fact["source"]]["text"]] + [frag[i]["text"] for i in pool])
    score = vecs[1:] @ vecs[0]
    if links:
        nb = neighbours(frag)
        one = nb[fact["source"]]
        two = set().union(*(nb[j] for j in one)) - one - {fact["source"]} if one else set()
        score = score + np.array([LINK1_BONUS if i in one else LINK2_BONUS if i in two else 0.0 for i in pool])
    return [pool[j] for j in np.argsort(-score)[:k]]


def meaning(fact, frag, embedder, k=K):
    return _topk(fact, frag, embedder, k)


def _hybrid(fact, frag, embedder, k, statuses, links):
    w = [i for i in words(fact, frag) if not (statuses and frag[i]["status"] in SKIP_STATUSES)]
    return w + [i for i in _topk(fact, frag, embedder, k, statuses, links) if i not in w]


def words_meaning(fact, frag, embedder, k=K):
    return _hybrid(fact, frag, embedder, k, statuses=False, links=False)


def plus_statuses(fact, frag, embedder, k=K):
    return _hybrid(fact, frag, embedder, k, statuses=True, links=False)


def plus_links(fact, frag, embedder, k=K):
    return _hybrid(fact, frag, embedder, k, statuses=True, links=True)


def with_judge(judge):
    """Ступень 2 поверх зафиксированной ступени 1 («+ статусы»): оставляем только то,
    что классификатор пометил «противоречит» или «нужно обновить» (H1)."""
    from .llm import FLAG

    def fn(fact, frag, embedder, k=K):
        old, new = frag[fact["source"]]["text"], fact["change"]
        return [i for i in plus_statuses(fact, frag, embedder, k) if judge.judge(old, new, frag[i])[0] in FLAG]
    return fn


def with_lights(judge, levels):
    """Светофор поверх ступени 1: в выдаче — фрагменты нужных цветов ({"red"} или {"red", "yellow"})."""
    from .llm import light

    def fn(fact, frag, embedder, k=K):
        old, new = frag[fact["source"]]["text"], fact["change"]
        return [i for i in plus_statuses(fact, frag, embedder, k) if light(judge.proba(old, new, frag[i])) in levels]
    return fn


def with_disagreement(judge, levels):
    """Светофор по несогласию способов: красный — классификатор сказал «противоречит / нужно обновить»;
    жёлтый — классификатор сказал «не трогать / не связано», но фрагмент прямо содержит то,
    что аналитик искал бы по словам. Сомнение возникает там, где способы спорят."""
    from .llm import FLAG

    def fn(fact, frag, embedder, k=K):
        old, new = frag[fact["source"]]["text"], fact["change"]
        lit = set(words(fact, frag))
        out = []
        for i in plus_statuses(fact, frag, embedder, k):
            color = "red" if judge.judge(old, new, frag[i])[0] in FLAG else "yellow" if i in lit else "green"
            if color in levels:
                out.append(i)
        return out
    return fn


METHODS = {
    "1 только слова": words,
    "2 только смысл": meaning,
    "3 слова + смысл": words_meaning,
    "4 + статусы": plus_statuses,
    "5 + связи": plus_links,
}


# --- оценка ----------------------------------------------------------------

def judge(fact, found):
    gold, soft, traps = set(fact["mentions"]), set(fact["soft"]), fact["traps"]
    got = set(found)
    return {"found": sorted(got & gold), "missed": sorted(gold - got), "soft": sorted(got & soft),
            "traps": sorted(got & set(traps)), "other": sorted(got - gold - soft - set(traps)),
            "n_gold": len(gold), "n_returned": len(got)}


def run(space, frag, embedder, k=K, methods=METHODS):
    return {name: [(fact, judge(fact, fn(fact, frag, embedder, k))) for fact in space["facts"]]
            for name, fn in methods.items()}


def summary(rows):
    g = sum(r["n_gold"] for _, r in rows)
    f = sum(len(r["found"]) for _, r in rows)
    ret = sum(r["n_returned"] for _, r in rows)
    return {"recall": f / g if g else float("nan"), "precision": f / ret if ret else float("nan"),
            "found": f, "gold": g, "returned": ret,
            "traps": sum(len(r["traps"]) for _, r in rows),
            "other": sum(len(r["other"]) for _, r in rows)}


def link_coverage(space, frag):
    """Сколько эталонных упоминаний вообще достижимо по связям от исходного фрагмента."""
    nb = neighbours(frag)
    hit = tot = 0
    for fact in space["facts"]:
        one = nb[fact["source"]]
        two = set().union(*(nb[j] for j in one)) if one else set()
        for m in fact["mentions"]:
            tot += 1
            hit += m in one or m in two
    return hit, tot


def table(res):
    rows = ["| способ | нашёл | полнота | точность | ловушек | всего выдал |", "|---|---|---|---|---|---|"]
    for name, r in res.items():
        s = summary(r)
        rows.append(f"| {name} | {s['found']} из {s['gold']} | {s['recall']:.0%} | {s['precision']:.0%}"
                    f" | {s['traps']} | {s['returned']} |")
    return rows


def report_md(space, frag, res, embedder_name, k):
    hit, tot = link_coverage(space, frag)
    out = [f"Пространство `{space['id']}` · фактов {len(space['facts'])} · фрагментов {len(frag)}"
           f" · эмбеддинги {embedder_name} · k = {k} (поиск по словам — без ограничения)",
           f"По связям (до 2 шагов) от изменённого фрагмента достижимо {hit} из {tot} эталонных упоминаний.", ""]
    out += table(res)
    out += ["", "**По фактам** — найдено / всего (ловушки в скобках):", "",
            "| факт | " + " | ".join(res) + " |", "|---|" + "---|" * len(res)]
    for i, fact in enumerate(space["facts"]):
        cells = []
        for name in res:
            r = res[name][i][1]
            t = f" ({', '.join(r['traps'])})" if r["traps"] else ""
            cells.append(f"{len(r['found'])}/{r['n_gold']}{t}")
        out.append(f"| {fact['id']} {fact['name']} | " + " | ".join(cells) + " |")
    out += ["", "**Что пропущено:**", ""]
    for name in res:
        miss = [f"{fact['id']}: {', '.join(r['missed'])}" for fact, r in res[name] if r["missed"]]
        out.append(f"- *{name}*: " + ("; ".join(miss) if miss else "ничего"))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("space")
    ap.add_argument("--embedder", choices=["st", "tfidf"], default="st")
    ap.add_argument("--k", type=int, default=K)
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--judge", choices=["local", "gigachat", "openai"], default=None,
                    help="добавить ступень 2 — классификатор пары на выбранной LLM")
    ap.add_argument("--drop-links", type=float, default=None,
                    help="удалить долю связей и сравнить «+ связи» с полными и урезанными связями")
    a = ap.parse_args()
    space, frag, errors = load(a.space)
    if errors:
        for e in errors:
            print("ОШИБКА", e)
        raise SystemExit(1)
    emb = STEmbedder() if a.embedder == "st" else TfidfEmbedder()
    if a.drop_links is not None:
        res = {"4 + статусы (без связей)": run(space, frag, emb, a.k, {"x": plus_statuses})["x"],
               "5 + связи, все": run(space, frag, emb, a.k, {"x": plus_links})["x"]}
        for share in (0.25, 0.5, 0.75):
            cut = drop_links(frag, share)
            hit, tot = link_coverage(space, cut)
            res[f"5 + связи, удалено {share:.0%} (достижимо {hit}/{tot})"] = \
                run(space, cut, emb, a.k, {"x": plus_links})["x"]
        print("\n".join(table(res)))
        return
    methods = dict(METHODS)
    judge = None
    if a.judge:
        from .llm import make_judge
        judge = make_judge(a.judge)
        methods[f"6 + классификатор ({judge.name})"] = with_judge(judge)
        if hasattr(judge.backend, "score"):
            methods["7 светофор: красные"] = with_lights(judge, {"red"})
            methods["7 светофор: красные + жёлтые"] = with_lights(judge, {"red", "yellow"})
        methods["8 светофор по несогласию: красные + жёлтые"] = with_disagreement(judge, {"red", "yellow"})
    res = run(space, frag, emb, a.k, methods)
    if judge is not None:
        per = judge.seconds / judge.calls if judge.calls else 0
        print(f"классификатор {judge.name}: новых вызовов {judge.calls}, в среднем {per:.1f} с на пару"
              f" (остальное из кэша {judge.path.name})")
    if a.md:
        print(report_md(space, frag, res, emb.name, a.k))
        return
    print("\n".join(table(res)))


if __name__ == "__main__":
    main()
