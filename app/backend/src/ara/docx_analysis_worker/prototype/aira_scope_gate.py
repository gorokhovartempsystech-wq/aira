"""Verify whether a numeric deadline answers a typed candidate on its own scope."""

import re
from decimal import Decimal

DURATION = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(минут\w*|мин|час\w*|сут\w*|д(?:ень|ня|ней))\b\.?", re.I
)
CLAUSE = re.compile(r"[;\n]+|(?<!\b(?i:мин)\.)(?<=[.!?])\s+|(?<=\b(?i:мин)\.)\s+(?=[А-ЯЁA-Z])")
NEXT_BOUND = re.compile(r",\s+(?=(?:не\s+более|не\s+позднее|в\s+течение)\s+\d)", re.I)
NONWORKING_DAYS = re.compile(r"\bв\s+нерабоч\w*\s+дн\w*", re.I)
STAGES = {
    "reaction": re.compile(
        r"реакци|реагир|\bотклик\w*\s+на\s+(?:обращени\w*|заявк\w*)"
        r"|\bна\s+(?:обращени\w*|заявк\w*)\b[^.!?;]{0,120}\bвыйти\s+на\s+связь\s+с\s+заявител\w*\b",
        re.I,
    ),
    "arrival": re.compile(r"прибы\w*|выезд\w*|прибыт\w*", re.I),
    "resolution": re.compile(r"устран\w*|восстанов\w*|\bисправ\w*|ликвидир\w*", re.I),
}
OBJECTS = {
    "critical": re.compile(r"\b(?:критическ|блокирующ)\w*", re.I),
    "minor": re.compile(r"\b(?:незначительн|некритическ|низкоприоритетн)\w*", re.I),
}
OFF = re.compile(r"\b(?:вне\s+рабоч\w*\s+врем\w*|нерабоч\w*\s+(?:врем\w*|час\w*))\b", re.I)
WORK = re.compile(r"\bрабоч\w*\s+(?:врем\w*|час\w*)\b", re.I)
ALL = re.compile(r"\bкруглосуточн\w*|24\s*[/×xх]\s*7", re.I)
COORDINATED = re.compile(r"\bрабоч\w*\s+и\s+(?:в\s+)?нерабоч\w*\s+врем\w*", re.I)
NEGATED = re.compile(
    r"\bне\s+(?:обязан\w*|гарантир\w*|регламентир\w*|установлен\w*|задан\w*)", re.I
)
LOWER_BOUND = re.compile(r"\b(?:не\s+(?:ранее|раньше|менее)|как\s+минимум|минимум)\s+\d", re.I)
FOLLOW_UP = re.compile(
    r"\b(?:после|по\s+факту)\s+(?:закрыти\w*|завершени\w*|исполнени\w*)\b"
    r"|\bподтвержден\w*\s+закрыти\w*\b",
    re.I,
)
WARRANTY_EOL_START = re.compile(
    r"\bгаранти\w*[^\d,;.!?\n]{0,120}?"
    r"\b\d+(?:\s*\([а-яё\s-]+\))?\s+(?:лет|год\w*|месяц\w*)\s+"
    r"после\s+(?:\bEOL\b|\bend[- ]of[- ]life\b|окончания\s+жизненного\s+цикла\b)",
    re.I,
)


def warranty_eol_start(text):
    """Check a warranty duration explicitly counted from an EOL event in its source."""
    for clause in CLAUSE.split(text):
        match = WARRANTY_EOL_START.search(clause)
        if not match or NEGATED.search(clause):
            continue
        prefix = clause[: match.start()]
        if not re.search(r"\b(?:без|нет)\s*$", prefix, re.I):
            return True
    return False


def modes(text):
    if ALL.search(text) or COORDINATED.search(text):
        return {"work", "off"}
    return {
        tag
        for tag, match in (("work", WORK.search(OFF.sub("", text))), ("off", OFF.search(text)))
        if match
    }


def labels(text, patterns):
    return {name for name, pattern in patterns.items() if pattern.search(text)}


def deadline_clauses(text):
    for clause in CLAUSE.split(text):
        parts = NEXT_BOUND.split(clause)
        if len(parts) == 2:
            left, right = map(modes, parts)
            if (left and right and left.isdisjoint(right)) or (
                left == {"work"} and not right and NONWORKING_DAYS.search(parts[1])
            ):
                yield from parts
                continue
        yield clause


def verify(target, fragments, classify_stage=None, *, prefer_rules=True):
    """Return source IDs only when an individual literal clause answers every requested field."""
    if target["stage"] not in STAGES or target["mode"] not in {"work", "off"}:
        raise ValueError("Unsupported target scope")
    if target["object"] is not None and target["object"] not in OBJECTS:
        raise ValueError("Unsupported object")
    answers = {}
    for identity, text in fragments.items():
        for clause in deadline_clauses(text):
            durations = DURATION.findall(clause)
            if (
                len(durations) != 1
                or NEGATED.search(clause)
                or LOWER_BOUND.search(clause)
                or target["mode"] not in modes(clause)
            ):
                continue
            if target["stage"] == "reaction" and FOLLOW_UP.search(clause):
                continue
            if target["object"] is not None and labels(clause, OBJECTS) != {target["object"]}:
                continue
            stages = labels(clause, STAGES)
            if classify_stage is not None and (not stages or not prefer_rules):
                stages = {classify_stage(clause)}
            if stages == {target["stage"]}:
                raw, unit = durations[0]
                factor = (
                    1
                    if unit.casefold().startswith("мин")
                    else 60
                    if unit.casefold().startswith("час")
                    else 1440
                )
                answers.setdefault(identity, set()).add(Decimal(raw.replace(",", ".")) * factor)
    return list(answers) if len(set().union(*answers.values())) == 1 else []
