"""Check the start of warranty coverage and the separate deadline for remedy."""
import re

from .aira_scope_gate import CLAUSE, warranty_eol_start


WARRANTY = re.compile(r"\bгаранти\w*", re.I)
TERM = re.compile(r"\b(\d+)\s*(?:\([а-яё\s-]+\)\s*)?(месяц\w*|год\w*|лет)\b", re.I)
START = re.compile(
    r"\b(?:с\s+(?:дат[ыа]|момент[а]?|дня)|со дня|от даты|после)\s+"
    r"(?:подписан\w*|при[её]м\w*|приняти\w*|поставк\w*|передач\w*|ввод\w*|получени\w*|"
    r"регистраци\w*|уведомлен\w*|обращени\w*|выявлен\w*|окончани\w*|завершени\w*)", re.I)
ACTION = re.compile(r"\b(?:устран\w*|исправ\w*|гарантийн\w+\s+ремонт)\b", re.I)
DEFECT = re.compile(r"недостат|дефект|неисправност|ошиб|недостоверност|гарантийн\w+\s+ремонт", re.I)
REMEDY_TIME = re.compile(
    r"\b\d+\s*(?:\([а-яё\s-]+\)\s*)?(?:(?:рабоч|календар)\w+\s+)?"
    r"(?:час\w*|сут\w*|дн\w*|день)\b", re.I)
RELATIVE_COVERAGE = re.compile(r",\s*котор\w+\s+(?:устанавлива|исчисля|начина)", re.I)
ARRIVAL = re.compile(r"\b(?:выезд|прибыти)\w*.{0,60}\bдиагностик\w*", re.I)
OBJECTS = {
    "work": r"\bработ\w*|обслуживани\w*",
    "part": r"запасн\w+\s+част|запчаст",
    "material": r"материал",
    "equipment": r"оборудован|прибор",
    "report": r"заключен|обследован|вывод",
    "system": r"систем|отделк",
}


def objects(text):
    return {kind for kind, pattern in OBJECTS.items() if re.search(pattern, text, re.I)}


def related(target, other):
    # An unspecified object in a different clause is insufficient to connect
    # two obligations. The same explicit objects can establish continuity.
    return bool(target and target <= other)


def warranty_clauses(fragments):
    for key, text in fragments.items():
        for clause in CLAUSE.split(text):
            marker = WARRANTY.search(clause)
            if marker:
                yield key, clause[marker.start():]


def review(fragments):
    coverage, starts, remedies = [], [], []
    for key, text in warranty_clauses(fragments):
        term = TERM.search(text)
        action = ACTION.search(text)
        start = START.search(text)
        answered = bool((start and (not action or start.start() < action.start())) or warranty_eol_start(text))
        subject = objects(text[:start.start()] if start else text)
        if answered:
            starts.append(subject)
        if term and (not action or term.start() < action.start()):
            durations = {int(count) * (1 if unit.casefold().startswith("месяц") else 12)
                         for count, unit in TERM.findall(text)}
            coverage.append((key, subject, answered, len(durations)))
    for key, text in fragments.items():
        for clause in CLAUSE.split(text):
            if WARRANTY.search(clause) and ACTION.search(clause) and DEFECT.search(clause):
                stage = RELATIVE_COVERAGE.split(clause, maxsplit=1)[0]
                remedies.append((key, stage, objects(stage), bool(REMEDY_TIME.search(stage))))

    cards = []
    joined = set()
    for key, scope, answered, duration_count in coverage:
        if not scope or answered or any(related(scope, other) for other in starts):
            continue
        ref = next((ref for ref, _, other, bound in remedies if not bound and related(scope, other)), None)
        if ref is not None:
            joined.add(ref)
            reason = ("Для работ и установленных деталей заданы разные гарантийные сроки. "
                      "Сверьте начало каждого срока и предельное время устранения гарантийного недостатка."
                      if duration_count > 1 and {"work", "part"} <= scope else
                      "Указана продолжительность гарантии и обязанность исправлять дефекты. "
                      "Сверьте начало гарантии и предельное время устранения дефекта.")
            cards.append((reason, [key, ref]))
        else:
            subject = " на работы и материалы" if scope == {"work", "material"} else ""
            cards.append((f"Указана продолжительность гарантии{subject}. "
                          "Сверьте, с какого события начинается её отсчёт.", [key]))

    ordered = list(fragments)
    positions = {key: index for index, key in enumerate(ordered)}
    for key, stage, scope, bound in remedies:
        if key in joined:
            continue
        if bound:
            if re.search(r"при\s+при[её]мк", stage, re.I) and WARRANTY.search(stage) and not START.search(stage):
                cards.append(("Один предельный срок устранения указан для недостатков при приёмке и в период гарантии. "
                              "Сверьте событие начала отсчёта отдельно для обоих случаев.", [key]))
            continue
        if any(known and related(scope, other) for _, _, other, known in remedies):
            continue
        if re.search(r"гарантийн\w+\s+ремонт", stage, re.I):
            # A bare reference to the contract may concern the offer, not the
            # entire defect. Defer unless that offer requirement is also linked.
            continue
        if re.search(r"замен\w*\s+товар", stage, re.I):
            i = positions[key]
            arrival = next((ref for ref in ordered[i + 1:i + 3]
                            if ARRIVAL.search(fragments[ref]) and REMEDY_TIME.search(fragments[ref])), None)
            if arrival is not None:
                cards.append(("Для выезда на диагностику указан срок. Сверьте отдельный предельный срок "
                              "устранения недостатка или завершения замены в рамках гарантии.", [key, arrival]))
                continue
        if re.search(r"в согласованн\w*.*срок", stage, re.I):
            reason = ("Срок устранения гарантийных дефектов стороны согласуют. Сверьте предельный срок "
                      "реакции или устранения, если срок ещё не согласован.")
        elif "report" in scope:
            reason = ("Ошибки заключения в гарантийный период исполнитель обязан исправить. "
                      "Сверьте предельный срок исправления с момента уведомления об ошибке.")
        else:
            reason = ("ТЗ обязывает устранить гарантийные дефекты. "
                      "Сверьте предельный срок исправления и событие начала его отсчёта.")
        cards.append((reason, [key]))
    return [{"kind": "unverifiable", "reason": reason, "fragment_ids": list(dict.fromkeys(refs))}
            for reason, refs in cards]
