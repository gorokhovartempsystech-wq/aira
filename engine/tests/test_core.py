"""Без модели и без LLM: TF-IDF вместо эмбеддингов, эвристика вместо классификатора.

    .venv/bin/python -m pytest -q
"""
from pathlib import Path

from fastapi.testclient import TestClient

from aira_ml import select, service
from aira_ml.analyze import Analyzer
from aira_ml.classify import NumericClassifier, quantities
from aira_ml.embed import TfidfEmbedder
from aira_ml.evaluate import load, metrics, run_arm
from aira_ml.lint import lint
from aira_ml.schema import AnalyzeRequest, Requirement

DATA = Path(__file__).parent.parent / "data" / "packets"


def test_lint_находит_неизмеримое_и_не_цепляет_составные_слова():
    codes = [h[0].code for h in lint("Система быстро обрабатывает ответ и т.д.")]
    assert codes == ["VAGUE", "OPEN_END"]
    assert lint("Поиск по Confluence-пространствам") == []
    assert lint("Это не просто настройка, а отдельный сервис") == []


def test_quantities_нормализует_единицы():
    assert [(v, u) for v, u, *_ in quantities("в течение 14 дней, не позднее 3 секунд")] == \
        [(14.0, "дни"), (3.0, "секунды")]


def test_эвристика_отличает_исключение_и_отменённую_версию():
    clf = NumericClassifier()
    a = "Покупатель может вернуть товар в течение 30 дней."
    b = "Покупатель может вернуть товар в течение 14 дней."
    assert clf.classify(a, b, 0.9).relation == "contradiction"
    assert clf.classify(a, b, 0.9, status="deprecated").relation == "version_update"
    assert clf.classify(a, b, 0.9, status="exception").relation == "independent"


def test_structured_не_берёт_отменённое_и_обсуждение_и_тянет_связи():
    p = load(DATA)[0]
    ch = p.changes[0]
    ids = {c.req.id for c in select.structured(ch.new_text, ch.requirement_id, p.requirements, TfidfEmbedder())}
    assert "ARC-RET-01" not in ids and "RET-007" not in ids
    assert {"RET-004", "RET-006"} <= ids
    sim = select.similarity(ch.new_text, ch.requirement_id, p.requirements, TfidfEmbedder())
    assert all(c.status is None for c in sim)


def test_бюджет_одинаковый():
    p = load(DATA)[0]
    ch = p.changes[0]
    for arm in select.SELECTORS.values():
        assert len(arm(ch.new_text, ch.requirement_id, p.requirements, TfidfEmbedder(), k=3)) <= 3


def test_оценка_считает_метрики_на_пакетах():
    mine = [p for p in load(DATA) if p.id in ("p01", "p02", "p03")]
    m = metrics(run_arm(mine, "structured", TfidfEmbedder(), NumericClassifier(), k=8))
    assert m["n_gold"] == 8 and m["n_correct"] == 6
    assert 0 <= m["Recall_contr"] <= 1 and 0 <= m["FAR"] <= 1


def test_сервис_отвечает_по_контракту(monkeypatch):
    # у TF-IDF косинусы ниже, чем у USER-bge-m3, поэтому порог темы снижен
    monkeypatch.setattr(service, "analyzer", lambda: Analyzer(TfidfEmbedder(), NumericClassifier(topic_threshold=0.2)))
    p = load(DATA)[0]
    body = AnalyzeRequest(change={"requirement_id": "RET-001", "new_text": p.changes[0].new_text},
                          requirements=p.requirements).model_dump()
    r = TestClient(service.app).post("/v1/analyze", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["skipped"] and d["skipped"][0]["check"] == "contradictions"
    contr = [i for i in d["issues"] if i["type"] == "contradiction"]
    assert contr and all(i["related"]["status"] for i in contr)


def test_без_target_и_change_422(monkeypatch):
    monkeypatch.setattr(service, "analyzer", lambda: Analyzer(TfidfEmbedder(), NumericClassifier()))
    body = {"requirements": [Requirement(id="A", text="x").model_dump()]}
    assert TestClient(service.app).post("/v1/analyze", json=body).status_code == 422


def test_пространство_возвраты_без_ошибок_и_лесенка_способов():
    from aira_ml import spaces
    space, frag, errors = spaces.load(Path(__file__).parent.parent / "data" / "spaces" / "vozvraty.json")
    assert errors == []
    emb = TfidfEmbedder()
    for fact in space["facts"]:
        w = set(spaces.words(fact, frag))
        assert w <= set(spaces.words_meaning(fact, frag, emb))
        for fn in (spaces.plus_statuses, spaces.plus_links):
            got = fn(fact, frag, emb)
            assert not any(frag[i]["status"] in spaces.SKIP_STATUSES for i in got)
            assert {i for i in w if frag[i]["status"] not in spaces.SKIP_STATUSES} <= set(got)
    # удаление всех связей превращает «+ связи» в «+ статусы» по составу кандидатов,
    # кроме связей через упоминание ID в тексте — их удалить нельзя
    cut = spaces.drop_links(frag, 1.0)
    assert all(f["links"] == [] for f in cut.values())


def test_разбор_ответа_llm():
    from aira_ml.llm import parse
    assert parse('{"ответ": "нужно обновить", "почему": "пример со старым сроком"}')[0] == "update"
    assert parse('Ответ: {"ответ": "Противоречит", "почему": "x"}')[0] == "contradiction"
    assert parse("думаю, тут не трогать — это исключение")[0] == "keep"
    assert parse("ерунда")[0] == "unrelated"
