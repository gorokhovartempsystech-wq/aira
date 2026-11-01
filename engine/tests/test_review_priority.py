from types import SimpleNamespace
import numpy as np
import pytest
from aira_ml.engine import Engine, checkable


def fragment(identity, text, section):
    return dict(id=identity,text=text,document=section,type="requirement",status="active")


def engine(contradiction):
    e=Engine.__new__(Engine)
    e.manifest={"version":"test"}
    e.nli_labels=["neutral","contradiction"]
    e.nli=SimpleNamespace(run=lambda a,b,**kwargs: np.tile([0.,10. if contradiction else -10.],(len(a),1)))
    e.embed=lambda f: np.array([[1.,0.],[.99,np.sqrt(1-.99**2)]])
    return e


@pytest.mark.parametrize("contradiction,disabled,expected", [
    (True,(),"contradiction"),(False,(),"duplicate"),
    (True,("contradiction",),"duplicate"),(True,("duplicate",),"contradiction")])
def test_near_duplicate_does_not_hide_confirmed_conflict(contradiction,disabled,expected):
    fs=[fragment("a","Сумма операции должна составлять не более 100 рублей.","Правила"),
        fragment("b","Минимальная сумма операции должна составлять 200 рублей.","API")]
    result=engine(contradiction).review(fs,disabled=disabled)
    assert [x["type"] for x in result["issues"] if x["type"] in ("duplicate","contradiction")]==[expected]


@pytest.mark.parametrize("text,section,expected",[
    ("Сумма заявки на оборудование не должна превышать 500 тысяч рублей.","Функциональные требования / Ограничение сумм оплаты",True),
    ("Пользователь должен оплачивать заказ банковской картой.","Оплата заказа",True),
    ("Заказчик перечисляет аванс в размере 30 процентов стоимости работ.","Условия",False),
    ("Размер первого платежа составляет 30 процентов стоимости работ.","Условия оплаты договора",False),
])
def test_payment_feature_is_not_a_contract_clause(text,section,expected):
    assert checkable(fragment("x",text,section)) is expected
