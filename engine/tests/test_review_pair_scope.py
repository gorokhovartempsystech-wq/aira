"""Regression tests for the source patch, with fixed scores at the verdict boundary."""
import numpy as np
import pytest

from aira_ml.engine import Engine


class IdenticalEmbeddings:
    def run(self, texts):
        return np.ones((len(texts), 1))


class StrongContradiction:
    def run(self, left, right):
        return np.tile([0.0, 0.0, 10.0], (len(left), 1))


LEFT = "Шлюз должен записывать отметку операции при восстановлении узла."
RIGHT = "Шлюз не должен записывать отметку операции при восстановлении узла."


@pytest.mark.parametrize("texts,expected", [
    ([LEFT, RIGHT], ["contradiction"]),
    ([LEFT, LEFT], ["duplicate"]),
    (["1. Промышленная среда", LEFT, "2. Тестовое окружение", RIGHT], []),
    (["ПРОМЫШЛЕННЫЙ КОНТУР:", LEFT, "Боевая среда проекта:", RIGHT], ["duplicate"]),
    (["Тестовая среда", LEFT, "Тестовое окружение:", RIGHT], ["contradiction"]),
    (["Журнал операций:", LEFT, "История операций:", RIGHT], ["contradiction"]),
    (["КАБИНЕТ ОПЕРАТОРА", LEFT, "КАБИНЕТ ГОСТЯ", RIGHT], ["duplicate"]),
])
def test_review_uses_scope_without_requiring_scope_headers_as_pair_candidates(texts, expected):
    model = Engine.__new__(Engine)
    model.manifest = {"version": "test"}
    model.emb = IdenticalEmbeddings()
    model.nli = StrongContradiction()
    model.nli_labels = ["entailment", "neutral", "contradiction"]
    fragments = [
        dict(id=str(i), text=text, status="active", type="фрагмент", document="D")
        for i, text in enumerate(texts)
    ]
    result = model.review(fragments)
    pair_issues = [issue for issue in result["issues"] if issue["related"]]
    assert [issue["type"] for issue in pair_issues] == expected
    assert result["checked"]["pairwise"] == 2
    for issue in pair_issues:
        assert issue["span"]["quote"] in (LEFT, RIGHT)
        assert issue["related"]["quote"] in (LEFT, RIGHT)
