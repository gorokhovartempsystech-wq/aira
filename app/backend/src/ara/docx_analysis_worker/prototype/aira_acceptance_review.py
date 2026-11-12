"""Emit acceptance cards for measurable properties and missing test evidence."""

import re

from .aira_scope_gate import CLAUSE
from .measurement_gaps import AVAILABILITY, PERCENT, availability_proof


def includes(text, *patterns):
    return all(re.search(pattern, text, re.I) for pattern in patterns)


def card(reason, *sources):
    return {"kind": "acceptance", "reason": reason, "fragment_ids": list(dict.fromkeys(sources))}


def availability_cards(fragments):
    clauses = [(key, clause) for key, text in fragments.items() for clause in CLAUSE.split(text)]
    for key, clause in clauses:
        metrics = re.findall(PERCENT, clause)
        if not includes(clause, AVAILABILITY) or len(metrics) != 1:
            continue
        metric = metrics[0]
        # A percentage explicitly declared unnecessary is not a missing
        # acceptance criterion. Keep this local to the availability phrase.
        negative = r"не\s+(?:требу\w*|нужн\w*|предусмотрен\w*)"
        if re.search(
            rf"(?:{AVAILABILITY})[^,;]{{0,80}}{re.escape(metric)}\s+{negative}", clause, re.I
        ) or re.search(
            rf"{negative}\s+(?:{AVAILABILITY})[^,;]{{0,80}}{re.escape(metric)}", clause, re.I
        ):
            continue
        # Within the source, the percentage and the availability target must
        # belong to the same phrase. Elsewhere require the same percentage.
        if not includes(clause, rf"(?:{AVAILABILITY})[^,;]{{0,80}}{re.escape(metric)}"):
            continue
        evidence = [part for _, part in clauses if includes(part, AVAILABILITY)]
        # Treat other plausible proof clauses as reasons to abstain when the
        # metric can refer to the same target. Conflicting percentages do not.
        missing = [
            label
            for field, label in (
                ("period", "расчётный период"),
                ("maintenance", "правило учёта плановых перерывов"),
            )
            if not any(availability_proof(part, field, metric) for part in evidence)
        ]
        if missing:
            yield card(f"Для проверки доступности {metric} уточните {' и '.join(missing)}.", key)


def disinfection_cards(fragments):
    requirements = [
        (key, text)
        for key, text in fragments.items()
        if includes(text, r"устойчив\w*|стойк\w*", r"дезинф|дезсредств")
    ]
    inspections = [
        (key, text)
        for key, text in fragments.items()
        if includes(text, r"провер\w*|при[её]мк", r"комплектн", r"дефект|упаковк")
    ]
    if len(requirements) != 1 or len(inspections) != 1:
        return
    if any(
        includes(
            clause, r"дезинф|дезсредств", r"испытан|сертификат|протокол|подтверж|цикл\w*|экспозиц"
        )
        for text in fragments.values()
        for clause in CLAUSE.split(text)
    ):
        return
    requirement, inspection = requirements[0][0], inspections[0][0]
    if requirement != inspection:
        yield card(
            (
                "Требуется стойкость к дезинфицирующим средствам. Перечень пр"
                "оверок при приёмке описывает комплектность и внешний осмотр."
                " Уточните, каким испытанием или документом подтверждают стой"
                "кость и по какому результату её принимают."
            ),
            requirement,
            inspection,
        )


HIDDEN_WORK = r"\bскрыт\w*\s+работ\w*"
HIDDEN_ACT = r"\bакт\w*\s+(?:освидетельствовани\w*\s+)?" + HIDDEN_WORK
NOTICE = r"\b(?:уведомл\w*|извещ\w*|вызов\w*|приглаш\w*)"
REPRESENTATIVE = r"\b(?:представител\w*|инженер\w*|заказчик\w*)"
CLOSURE = r"\b(?:закры\w*|задел\w*|последующ\w*\s+работ\w*)"
ABSENCE = r"\b(?:неявк\w*|отсутств\w*|не\s+(?:яви\w*|прибыл\w*))"
REPORT = r"\b(?:отч[её]т\w*|заключени\w*)\b"
REVISION = r"\b(?:доработ\w*|исправлен\w*|устран\w*\s+замечан\w*)\b"
REVISION_INTERVAL = (
    "\\b(?:в\\s+течение|не\\s+позднее\\s+чем\\s+через)\\s+\\d+\\s*(?:"
    "\\([^)]*\\)\\s*)?(?:(?:рабоч\\w*|календарн\\w*)\\s+)?(?:дн\\w*|с"
    "ут\\w*|час\\w*)"
)
REQUEST_TRIGGER = (
    "(?:с\\s+(?:момента|даты)|после)\\s+(?:получен\\w*|направлен\\w*)"
    "\\s+(?:запрос\\w*|замечан\\w*|требовани\\w*)"
)
CUSTOMER_REVISION_REQUEST = re.compile(
    rf"\bзаказчик\s+(?:вправе|может)\s+запросить[^.!?]{{0,95}}{REVISION}\s+({REPORT})"
    r"(?:\s+((?-i:[А-ЯЁA-Z]{2,})\b))?",
    re.I,
)
SERVING_TEMPERATURE = (
    r"\bтемператур\w*\s+(?:подачи|выдачи)\s+(?:горячих\s+|холодных\s+)?блюд\b"
    r"|\bтемператур\w*\s+(?:горячих\s+|холодных\s+)?блюд\s+при\s+(?:подаче|выдаче)\b"
)
ACCEPTANCE_CHECKLIST = r"\bпри\s+при[её]мке\s+провер\w*"
TEMPERATURE_LIMIT = r"(?<!\w)[+−-]?\d+(?:[.,]\d+)?\s*°\s*[cс]\b"
TEMPERATURE_MEASUREMENT = (
    r"\b(?:измеря\w*|замеря\w*|измерен\w*|замер\w*)\b[^.!?;]{0,100}"
    r"\b(?:термометр\w*|термощуп\w*|щуп\w*)\b"
)
COVERAGE = (
    r"\bрадиопокрыти\w*|\bwi[\s-]?fi[\s-]?покрыти\w*"
    r"|\bпокрыти\w*[^.!?;]{0,60}\b(?:радиосвяз\w*|блвс|wi[\s-]?fi)\b"
)
COVERAGE_DUTY = r"\b(?:долж\w*|обязан\w*|обеспеч\w*|устойчив\w*|бесперебойн\w*)\b"
COVERAGE_TEST = r"\b(?:радиообследован\w*|замер\w*|измер(?:ен|я)\w*|испытан\w*)\b"
COVERAGE_WIFI = r"\b(?:блвс|wi[\s-]?fi)\b"
COVERAGE_RADIO = r"\b(?:радиопокрыти\w*|радиосвяз\w*)\b"
COVERAGE_LEVEL = r"[+−-]?\d+(?:[.,]\d+)?\s*(?:дбм|dbm)\b"
COVERAGE_DESIGN = (
    r"\bдо\s+монтажа\b|\bдля\s+(?:проекта|проектирования|планирования)\b"
    r"|\bна\s+(?:этапе|стадии)\s+(?:радио)?проектирования\b"
)
COVERAGE_ACCEPTANCE = (
    r"\bпри\s+(?:при[её]мке|сдаче)\b|\bпосле\s+(?:монтажа|пусконаладочн\w*\s+работ)\b"
)
COVERAGE_RECORD = r"\b(?:протокол|отч[её]т)\w*\b"
COVERAGE_NO_RECORD = (
    rf"{COVERAGE_RECORD}[^,;.!?]{{0,85}}\bне\s+"
    r"(?:требу\w*|оформля\w*|предоставля\w*|составля\w*)\b"
)
UPS = r"\bибп\b|источник\w*\s+бесперебойного\s+питания"
UPS_TEST = r"\b(?:испытан\w*|тестирован\w*|провер\w*\s+работоспособност\w*)\b"
UPS_GENERIC_MODE = r"\b(?:различн\w*|разн\w*|нескольк\w*)\s+режим\w*\b"
UPS_VOLTAGE = r"\bнапряжени\w*\b"
UPS_CURRENT = r"\bток\w*\b"
UPS_CAPACITY = r"\b[её]мкост\w*\b"
UPS_MEASUREMENT = r"\b(?:замер\w*|измер\w*)\b"
UPS_OTHER_STAGE = r"\b(?:заводск\w*\s+испытан\w*|до\s+ремонта|входн\w*\s+контрол\w*)\b"
UPS_MODE_MARKERS = (
    r"\bот\s+сет[ьи]\b",
    r"\bот\s+(?:акб|батаре\w*|аккумулятор\w*)\b",
    r"\bбайпас\w*\b",
)
UPS_LIMIT = r"\b(?:допуск\w*|отклонени\w*|не\s+(?:более|менее|выше|ниже))\b|±"
UPS_VALUE = r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:%|[вvаa]\b|а\s*[·⋅-]\s*ч\b)"


def hidden_work_cards(fragments):
    acts = [key for key, text in fragments.items() if includes(text, HIDDEN_ACT)]
    if not acts:
        return
    scope = [
        clause
        for text in fragments.values()
        for clause in CLAUSE.split(text)
        if includes(clause, HIDDEN_WORK)
    ]
    # Inspect an explicit instruction about closure or a no-show. A general
    # list of deliverables or a reference to a representative cannot answer it.
    for text in scope:
        if includes(
            text, CLOSURE, ABSENCE, REPRESENTATIVE, r"разреш\w*|допуска\w*|запрещ\w*|перенос\w*"
        ) or includes(
            text,
            r"прежде чем\s+закры|до\s+закрыти|только\s+после",
            r"сдать|при[её]мк|осмотр|подписан\w*\s+акт",
        ):
            return
    notice = any(includes(text, NOTICE, REPRESENTATIVE) for text in scope)
    missing = (
        "Сверьте, когда уведомлять представителя и можно ли закрывать работы, если он не явился."
        if not notice
        else "Сверьте, можно ли закрывать работы, если уведомлённый представитель не явился."
    )
    yield card(f"Для скрытых работ предусмотрен акт освидетельствования. {missing}", *acts)


def report_revision_cards(fragments):
    """Check the contractor's correction cycle after a customer's request."""
    requests = [
        (key, match)
        for key, text in fragments.items()
        if includes(text, r"при[её]мк") and (match := CUSTOMER_REVISION_REQUEST.search(text))
    ]
    if len(requests) != 1:
        return
    key, request = requests[0]
    report, qualifier = request.groups()
    document = (
        r"\bотч[её]т\w*\b"
        if report.casefold().startswith(("отчет", "отчёт"))
        else r"\bзаключени\w*\b"
    )
    if qualifier:
        document += rf"\s+{re.escape(qualifier)}\b"
    clauses = [
        clause
        for text in fragments.values()
        for clause in CLAUSE.split(text)
        if includes(clause, document) and not includes(clause, r"гарантийн")
    ]
    correction = any(
        includes(
            clause,
            rf"\b(?:исполнитель|подрядчик)\b[^,:]{{0,100}}{REVISION}",
            REVISION_INTERVAL,
            REQUEST_TRIGGER,
        )
        for clause in clauses
    )
    recheck = any(
        includes(
            clause,
            r"повторн\w*\s+(?:провер\w*|при[её]мк\w*)|повторно\s+(?:провер\w*|принима\w*)",
            REVISION,
        )
        for clause in clauses
    )
    missing = []
    if not correction:
        missing.append("срок доработки с момента получения замечаний")
    if not recheck:
        missing.append("порядок повторной проверки исправлений")
    if missing:
        yield card(
            (
                "Заказчик может запросить доработку "
                "документа при приёмке. Уточните "
                f"{' и '.join(missing)}"
                "."
            ),
            key,
        )


def serving_temperature_cards(fragments):
    requirement = [key for key, text in fragments.items() if includes(text, SERVING_TEMPERATURE)]
    checks = [
        key
        for key, text in fragments.items()
        if includes(text, ACCEPTANCE_CHECKLIST, r"блюд|врем\w*\s+подачи")
    ]
    if not requirement or len(checks) != 1:
        return
    scope = [
        part
        for text in fragments.values()
        for part in CLAUSE.split(text)
        if includes(part, SERVING_TEMPERATURE) and not includes(part, r"температур\w*\s+хранени")
    ]
    fields = [
        name
        for name, pattern in (
            ("допустимые температуры подачи для разных блюд", TEMPERATURE_LIMIT),
            ("способ измерения температуры при подаче", TEMPERATURE_MEASUREMENT),
        )
        if not any(includes(part, pattern) for part in scope)
    ]
    if fields:
        yield card(
            (
                "ТЗ требует соблюдения температуры п"
                "одачи блюд и отдельно перечисляет п"
                "роверки при приёмке. Сверьте "
                f"{' и '.join(fields)}"
                "."
            ),
            requirement[0],
            checks[0],
        )


def coverage_cards(fragments):
    requirements = [
        key
        for key, text in fragments.items()
        if includes(text, COVERAGE, COVERAGE_DUTY, r"объект|территори|маршрут|площад")
    ]
    if len(requirements) != 1:
        return
    wifi = includes(fragments[requirements[0]], COVERAGE_WIFI)
    topic = COVERAGE_WIFI if wifi else COVERAGE_RADIO
    clauses = [part for text in fragments.values() for part in CLAUSE.split(text)]
    evidence = [
        part
        for part in clauses
        if includes(part, topic)
        and (not includes(part, COVERAGE_DESIGN) or includes(part, COVERAGE_ACCEPTANCE))
    ]
    levels = any(
        includes(part, COVERAGE_LEVEL, r"мин\b|не\s+ниже|уров\w*\s+сигнал") for part in evidence
    )
    # In a table projection the measurement name and the values can be separate fragments.
    source = list(fragments.values())
    levels |= any(
        includes(label, r"уров\w*\s+сигнал\w*[^.!?;]{0,20}\bмин\b")
        and includes(" ".join(source[max(0, i - 6) : i]), topic)
        and re.fullmatch(r"\s*" + COVERAGE_LEVEL + r"\s*", source[i + 1], re.I)
        for i, label in enumerate(source[:-1])
    )
    points = any(
        includes(part, COVERAGE_TEST, r"контрольн\w*\s+точк\w*|сетк\w*\s+замер\w*")
        for part in evidence
    )
    records = any(
        not includes(part, COVERAGE_NO_RECORD)
        and (
            includes(part, COVERAGE_RECORD, COVERAGE_TEST)
            or includes(part, r"результат\w*\s+тестирован", r"финальн\w*\s+обследован")
        )
        for part in evidence
    )
    fields = [
        label
        for label, present in (
            ("минимально допустимое качество связи", levels),
            ("контрольные точки замеров", points),
            ("форму подтверждения результатов", records),
        )
        if not present
    ]
    if fields:
        yield card(
            "ТЗ задаёт область обязательного покрытия связью. "
            f"Для приёмки уточните {', '.join(fields)}.",
            requirements[0],
        )


def ups_test_cards(fragments):
    entries = list(fragments.items())
    tests = [i for i, (_, text) in enumerate(entries) if includes(text, UPS_TEST, UPS_GENERIC_MODE)]
    if len(tests) != 1:
        return
    test = tests[0]
    nearby = entries[max(0, test - 8) : test]
    electrical = [
        key
        for key, text in nearby
        if includes(text, UPS, UPS_MEASUREMENT, UPS_VOLTAGE, UPS_CURRENT)
    ]
    batteries = [
        key
        for key, text in nearby
        if includes(text, UPS_MEASUREMENT, UPS_CAPACITY, r"акб|батаре|аккумулятор")
    ]
    if len(electrical) != 1 or len(batteries) != 1:
        return
    proof = [
        part
        for text in fragments.values()
        for part in CLAUSE.split(text)
        if includes(part, UPS, UPS_TEST) and not includes(part, UPS_OTHER_STAGE)
    ]
    named_modes = any(
        sum(includes(part, marker) for marker in UPS_MODE_MARKERS) >= 2 for part in proof
    )
    metrics = (
        (UPS_VOLTAGE, "выходного напряжения"),
        (UPS_CURRENT, "выходного тока"),
        (UPS_CAPACITY, "ёмкости"),
    )
    limit_clauses = [
        clause
        for part in proof
        for clause in re.split(r"(?<!\d),|,(?!\d)", part)
        if includes(clause, UPS_LIMIT, UPS_VALUE)
    ]
    missing_limits = [
        name
        for pattern, name in metrics
        if not any(includes(clause, pattern) for clause in limit_clauses)
    ]
    questions = []
    if not named_modes:
        questions.append("какие режимы ИБП обязательно испытать")
    if missing_limits:
        questions.append(
            (
                "какие допуски для данной модели ИБП"
                " применить к результатам замера "
                f"{', '.join(missing_limits)}"
            )
        )
    if questions:
        yield card(
            "ТЗ предусматривает замеры параметров ИБП и испытания в разных режимах. "
            f"Уточните, {' и '.join(questions)}.",
            electrical[0],
            batteries[0],
            entries[test][0],
        )


def review(fragments):
    """Use all source fragments so that a proof outside a candidate window can suppress it."""
    return [
        *availability_cards(fragments),
        *disinfection_cards(fragments),
        *hidden_work_cards(fragments),
        *report_revision_cards(fragments),
        *serving_temperature_cards(fragments),
        *coverage_cards(fragments),
        *ups_test_cards(fragments),
    ]
