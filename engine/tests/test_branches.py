"""Адаптер веток декомпозиции: разбор обоих форматов и фильтр по согласию учителя (без LLM)."""
import json

from aira_ml.branches import GENERIC, branches_of, candidate_pairs, run


def frag(i, text):
    return {"id": i, "type": "функциональное требование", "document": "Спецификация", "status": "active",
            "links": [], "text": text}


FRAGS = [frag("H1", "Клиент подаёт заявление через веб-интерфейс."),
         frag("D1", "Форма заявления открывается из личного кабинета."),
         frag("D2", "Заявке присваивается номер после отправки."),
         frag("D3", "POST /claims принимает данные заявления."),
         frag("N1", "Отзыв заявления возможен до начала рассмотрения.")]

FABLE = {"id": "genf-test", "source": "synthetic-llm", "fragments": FRAGS, "facts": [],
         "branches": [{"id": "B1", "high": "H1", "change": "Клиент подаёт заявление только через мобильное приложение.",
                       "affected": ["D1"], "not_affected": ["D2", "D3"], "hard_negatives": ["N1"]}]}

V4 = {"id": "gen4-test", "source": "synthetic-llm-decomposition", "fragments": FRAGS,
      "facts": [{"id": "F1", "source": "H1", "change": "Клиент подаёт заявление только через мобильное приложение.",
                 "mentions": {"D1": "детализирует"}, "soft": {},
                 "traps": {"D2": "та же ветка, правка не касается", "D3": "та же ветка, правка не касается",
                           "N1": "другая ветка"}}]}


def test_both_formats_give_same_branch():
    a, ea = branches_of(FABLE)
    b, eb = branches_of(V4)
    assert not ea and not eb
    for key in ("high", "affected", "not_affected", "hard_negatives"):
        assert a[0][key] == b[0][key]


def test_broken_branch_is_reported():
    bad = json.loads(json.dumps(FABLE))
    bad["branches"][0]["hard_negatives"] = ["D1"]           # тот же фрагмент в двух группах
    bs, errors = branches_of(bad)
    assert not bs and errors


def test_candidate_pairs_expectations():
    (b,), _ = branches_of(FABLE)
    rows = candidate_pairs(FABLE, b)
    change = {(fr["id"], exp) for kind, _, _, fr, exp in rows if kind == "change"}
    trace = {(fr["id"], exp) for kind, _, new, fr, exp in rows if kind == "trace" and new.endswith(GENERIC)}
    assert change == {("D1", True), ("D2", False), ("D3", False), ("N1", False)}
    assert trace == {("D1", True), ("D2", True), ("D3", True), ("N1", False)}


class FakeJudge:
    """Учитель-заглушка: «затронуто» только D1 и, по ошибке, D3."""
    def judge(self, old, new, fr):
        return ("update", "") if fr["id"] in ("D1", "D3") else ("keep", "")


def fake_dep(high, low):
    return "Отзыв" not in low                                 # всё, кроме соседней ветки, «зависит»


def test_only_agreeing_pairs_are_kept(tmp_path):
    p = tmp_path / "s-f.json"
    p.write_text(json.dumps(FABLE, ensure_ascii=False), encoding="utf-8")
    kept, stats, _ = run([str(p)], tmp_path / "out.jsonl", judge=FakeJudge(), dep=fake_dep)
    ids = {(r["variant"], r["fragment"]["id"], r["label"]) for r in kept}
    assert ("change", "D3", "update") not in ids               # учитель не согласен с картой — пара выброшена
    assert ("change", "D1", "update") in ids and ("change", "N1", "keep") in ids
    assert ("trace", "N1", "unrelated") in ids and ("trace", "D2", "update") in ids
    assert stats[("change", "exp_no_said_yes")] == 1
