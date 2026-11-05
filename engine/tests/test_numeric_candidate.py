"""Synthetic numerical checks only; no customer/externally sourced text."""
import pytest

from experiments.numeric_candidate.numeric_v4 import compare, filter_policy


@pytest.mark.parametrize('a,b,expected', [
    ('Срок хранения заказа не должен составлять ровно 17 дней.', 'Срок хранения заказа ровно 17 дней.', 'conflict'),
    ('Срок хранения заказа не должен составлять ровно 17 дней.', 'Срок хранения заказа ровно 18 дней.', 'compatible_bounds'),
    ('Срок хранения заказа запрещено хранить менее 17 дней.', 'Срок хранения заказа не более 16 дней.', 'conflict'),
    ('TTFB не должен быть более 110 мс.', 'TTFB не менее 130 мс.', 'conflict'),
    ('TTFB не более 110 мс.', 'TTFB не менее 100 мс.', 'compatible_bounds'),
    ('TTFB не обязательно должен составлять ровно 110 мс.', 'TTFB ровно 120 мс.', 'unknown'),
    ('Логи в hot storage хранятся не менее 40 дней, кроме тестовых логов.', 'Тестовые логи в hot storage хранятся не более 10 дней.', 'not_applicable'),
    ('Все логи в hot storage хранятся не менее 40 дней.', 'Тестовые логи в hot storage хранятся не более 10 дней.', 'conflict'),
    ('Audit log сервиса оплаты хранится не менее 8 месяцев.', 'Audit log сервиса доставки хранится не более 4 месяцев.', 'different_scope'),
    ('Во всех режимах TTFB не более 430 мс.', 'В аварийном режиме TTFB не менее 550 мс.', 'conflict'),
])
def test_numeric_scope_negation_and_general_rules(a, b, expected):
    assert compare(a, b)['verdict'] == expected


def test_numeric_compatibility_cannot_cancel_other_semantic_claims():
    a = 'Срок хранения заказа должен составлять ровно 17 дней.'
    b = 'Срок хранения заказа не должен превышать 20 дней.'
    assert compare(a, b)['suppress_nli_compatible']
    assert not compare(a + ' Удаление запрещено.', b + ' Удаление обязательно.')['suppress_nli_compatible']
    assert not filter_policy(a, a)['suppress_duplicate']
