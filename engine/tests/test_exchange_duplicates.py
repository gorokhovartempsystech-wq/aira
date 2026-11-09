import numpy as np
import pytest

from aira_ml.engine import Engine


class IdenticalEmbeddings:
    def run(self, texts):
        return np.ones((len(texts), 1))


@pytest.mark.parametrize("left,right,expected", [
    ("4.1. Направление 1С → АИС «Компетенция»",
     "4.2. Направление АИС «Компетенция» → 1С", []),
    ("4.1. Направление 1С → АИС «Компетенция»",
     "4.2. Направление АИС «Компетенция» ← 1С", ["duplicate"]),
    ("4.1. Направление 1С → АИС «Компетенция»",
     "4.2. Направление 1С → АИС «Компетенция»", ["duplicate"]),
    ("Направление 1С -> АИС «Компетенция» при первичной загрузке",
     "Направление 1С -> АИС «Компетенция» при повторной загрузке", []),
    ("Направление 1С → АИС «Компетенция», если загрузка первичная",
     "Направление 1С → АИС «Компетенция», если загрузка первичная", ["duplicate"]),
    ("Модуль должен сохранять журнал операций",
     "Модуль должен сохранять журнал операций", ["duplicate"]),
])
def test_duplicate_detection_respects_exchange_scope(left, right, expected):
    model = Engine.__new__(Engine)
    model.manifest = {"version": "test"}
    model.emb = IdenticalEmbeddings()
    model._emb = model.emb.run
    for texts in ((left, right), (right, left)):
        fragments = [
            dict(id=str(i), text=text, status="active", type="фрагмент", document="D")
            for i, text in enumerate(texts)
        ]
        result = model.review(fragments, disabled=("contradiction",))
        assert [issue["type"] for issue in result["issues"]] == expected
