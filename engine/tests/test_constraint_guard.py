import pytest
from aira_ml.constraint_guard import verdict
from test_review_priority import engine, fragment


@pytest.mark.parametrize('lower,expected',[(400,False),(500,False),(600,True)])
def test_closed_intervals(lower,expected):
    assert verdict('Сумма заявки ALPHA должна составлять не более 500 рублей.',f'Сумма заявки ALPHA должна составлять не менее {lower} рублей.') is expected


@pytest.mark.parametrize('a,b',[
 ('Максимальная сумма составляет 1000 рублей.','Максимальная сумма составляет 500 рублей.'),
 ('Сумма заявки ALPHA должна составлять ровно 500 рублей.','Сумма заявки BETA должна составлять ровно 600 рублей.'),
 ('Сумма заявки должна составлять ровно 500 рублей, если клиент новый.','Сумма заявки должна составлять ровно 600 рублей.'),
 ('Время обработки должно составлять ровно 5 рабочих дней.','Время обработки должно составлять ровно 7 календарных дней.'),
])
def test_unknown_scope_is_not_overruled(a,b):
    assert verdict(a,b) is None


def test_number_format_and_paraphrase():
    assert verdict('Сумма заявки ALPHA не должна превышать 1 000 рублей.','Сумма заявки ALPHA должна быть не меньше 1500 рублей.') is True


def test_same_section_does_not_suppress_conflict():
    fs=[fragment('a','Системе разрешено удалять заявку после подтверждения.','Правила'),fragment('b','Системе запрещено удалять заявку после подтверждения.','Правила')]
    assert any(x['type']=='contradiction' for x in engine(True).review(fs)['issues'])


def test_identical_text_overrides_wrong_nli():
    fs=[fragment('a','Длина поля ALPHA должна составлять ровно 8 символов.','A'),fragment('b','Длина поля ALPHA должна составлять ровно 8 символов.','B')]
    assert not any(x['type']=='contradiction' for x in engine(True).review(fs)['issues'])


def test_numeric_conflict_overrides_low_nli():
    fs=[fragment('a','Сумма заявки ALPHA должна составлять не более 500 рублей.','A'),fragment('b','Сумма заявки ALPHA должна составлять не менее 600 рублей.','B')]
    issues=engine(False).review(fs)['issues']
    assert any(x['type']=='contradiction' and 'Числовые ограничения' in x['explanation'] for x in issues)


def test_quoted_whitespace_not_treated_as_identical():
    fs=[fragment('a','Поле должно содержать строку "hello world".','A'),fragment('b','Поле должно содержать строку "hello  world".','B')]
    assert any(x['type']=='contradiction' for x in engine(True).review(fs)['issues'])


def test_complementary_bounds_do_not_become_a_duplicate():
    fs=[fragment('a','Сумма заявки ALPHA должна составлять не более 500 рублей.','A'),fragment('b','Сумма заявки ALPHA должна составлять не менее 400 рублей.','B')]
    assert not engine(True).review(fs)['issues']


def test_unnamed_entity_across_sections_does_not_force_numeric_conflict():
    fs=[fragment('a','Сумма заявки должна составлять не более 500 рублей.','Продукт A'),fragment('b','Сумма заявки должна составлять не менее 600 рублей.','Продукт B')]
    assert not any(x['type']=='contradiction' for x in engine(False).review(fs)['issues'])
