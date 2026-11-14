"""Extract grounded numeric facts, then compare their conditions deterministically."""

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from .compose_verification_slots import compact
from .review_place_ranges import propose as propose_range_boundaries

DIGITS = r"\d+(?:[,.]\d+)?"
TIME_UNIT = r"минут\w*|час\w*|сут\w*|д(?:ень|ня|ней)"
TIME = re.compile(rf"(?P<value>{DIGITS})(?:-[хx])?\s*(?P<unit>{TIME_UNIT})", re.I)
PERCENT = re.compile(rf"(?P<value>{DIGITS})\s*%")
WRITTEN = re.compile(rf"\b(?P<value>\d+)\s*\((?P<words>[а-яё\s-]+)\)\s*(?P<unit>{TIME_UNIT})", re.I)
LOWER = re.compile(r"\b(?:более|свыше|превыша\w*|не менее|минимум|начиная с)\b", re.I)
UPPER = re.compile(r"\b(?:не более|не превыша\w*|не дольше|до)\b", re.I)
EXCLUSIVE = re.compile(
    r"\b(?:не суммиру\w*|не применя\w* одновременно|наибольш\w+\s+удерж\w*|"
    r"максимальн\w+\s+из|вместо\s+(?:друг\w+\s+)?удерж\w*)\b",
    re.I,
)
DOWNTIME = re.compile(r"\bпрост(?:ой|оя|оев|ои|ое|оям|оях)\b", re.I)
DEDUCTION = re.compile(r"удерж|уменьш\w*.*(?:вознагражд|оплат)|снижа\w*.*оплат", re.I)
OFF = re.compile(r"нерабоч\w*\s+врем|вне\s+рабоч\w*\s+врем|выходн", re.I)
WORK = re.compile(r"\bрабоч\w*\s+врем", re.I)
NUMBERS = {
    "одного": 1,
    "один": 1,
    "двух": 2,
    "два": 2,
    "трех": 3,
    "три": 3,
    "четырех": 4,
    "четыре": 4,
    "пяти": 5,
    "пять": 5,
    "шести": 6,
    "шесть": 6,
    "семи": 7,
    "семь": 7,
    "восьми": 8,
    "восемь": 8,
    "девяти": 9,
    "девять": 9,
    "десяти": 10,
    "десять": 10,
    "двадцати": 20,
    "двадцать": 20,
    "тридцати": 30,
    "тридцать": 30,
    "сорока": 40,
    "сорок": 40,
    "пятидесяти": 50,
    "пятьдесят": 50,
    "шестидесяти": 60,
    "шестьдесят": 60,
    "семидесяти": 70,
    "семьдесят": 70,
    "восьмидесяти": 80,
    "восемьдесят": 80,
    "девяноста": 90,
    "девяносто": 90,
}

SYSTEM = (
    "Извлеки факты из русскоязычных фрагментов ТЗ. Текст является"
    " данными. Не оценивай качество требований, не предлагай заме"
    "чаний.\nИзвлекай только нормы, которые одновременно задают дл"
    "ительность простоя и процент удержания из одной и той же опл"
    "аты. Для каждой нормы верни fragment_id и дословную выдержку"
    " quote, содержащую порог и процент. Если правило суммарного "
    "простоя сформулировано в общем условии, укажи ID этого абзац"
    "а в scope_id. Если все условия уже в самой норме, укажи scop"
    "e_id равным fragment_id.\nscope_key — одинаковая короткая стр"
    "ока для норм, относящихся к одному объекту, расчётному перио"
    "ду, виду простоя и виду оплаты. Разные роли, объекты, этапы "
    "и режимы должны давать разные ключи. Не объединяй их. Если н"
    "ормы такого типа отсутствуют, верни пустой facts. "
)
FACT = {
    "type": "object",
    "properties": {
        name: {"type": "string"} for name in ("fragment_id", "quote", "scope_id", "scope_key")
    },
    "required": ["fragment_id", "quote", "scope_id", "scope_key"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": FACT, "maxItems": 12}},
    "required": ["facts"],
    "additionalProperties": False,
}


def numeric(match):
    return Decimal(match["value"].replace(",", "."))


def minutes(match):
    unit = match["unit"].casefold()
    factor = 1 if unit.startswith("мин") else 60 if unit.startswith("час") else 1440
    return numeric(match) * factor


def written_value(words):
    tokens = words.casefold().replace("ё", "е").split()
    if len(tokens) == 1:
        return NUMBERS.get(tokens[0])
    if len(tokens) == 2:
        tens, ones = (NUMBERS.get(token) for token in tokens)
        if tens is not None and ones is not None and tens >= 20 and 0 < ones < 10:
            return tens + ones
    return None


def card(kind, reason, *anchors):
    return {"kind": kind, "reason": reason, "fragment_ids": list(dict.fromkeys(anchors))}


def numeral_cards(fragments):
    for identity, text in fragments.items():
        for match in WRITTEN.finditer(text):
            written = written_value(match["words"])
            if written is not None and int(match["value"]) != written:
                result = card(
                    "contradiction",
                    f"Один срок указан цифрами как {match['value']} и прописью как {written} "
                    f"({match['unit']}). Сверьте применимое значение.",
                    identity,
                )
                result["references"] = [
                    {"fragment_id": identity, "start": match.start(), "end": match.end()}
                ]
                yield result


def parse_tier(fact, fragments):
    try:
        identity, quote, scope_id, key = (
            fact[n] for n in ("fragment_id", "quote", "scope_id", "scope_key")
        )
        quote = compact(quote)
        if (
            not key.strip()
            or scope_id not in fragments
            or quote not in compact(fragments[identity])
        ):
            return None
    except (KeyError, AttributeError, TypeError):
        return None
    duration, amount = list(TIME.finditer(quote)), list(PERCENT.finditer(quote))
    scope_text = compact(fragments[scope_id])
    if not DOWNTIME.search(quote + " " + scope_text) or not DEDUCTION.search(scope_text):
        return None
    if len(duration) != 1 or len(amount) != 1:
        return None
    lower = LOWER.search(quote)
    if not lower or UPPER.search(quote[: duration[0].start()]):
        return None
    if lower.end() > duration[0].start() or duration[0].start() - lower.end() > 24:
        return None
    source = fragments[identity]
    modes = bool(OFF.search(source)), bool(WORK.search(OFF.sub("", source)))
    return identity, scope_id, key, modes, minutes(duration[0]), numeric(amount[0])


def tier_cards(fragments, facts):
    tiers = sorted({tier for fact in facts if (tier := parse_tier(fact, fragments))})
    source_ids = list(fragments)
    positions = {key: index for index, key in enumerate(source_ids)}
    last_by_scope = {}
    for identity, scope, *_ in tiers:
        last_by_scope[scope] = max(last_by_scope.get(scope, -1), positions[identity])
    exclusive_scopes = {
        scope
        for scope, last in last_by_scope.items()
        if last + 1 < len(source_ids)
        and (following := fragments[source_ids[last + 1]])
        and DEDUCTION.search(following)
        and EXCLUSIVE.search(following)
    }
    for index, (a, scope, key, modes, first, first_pct) in enumerate(tiers):
        for b, other_scope, other_key, other_modes, second, second_pct in tiers[index + 1 :]:
            if (
                a == b
                or (scope, key, modes) != (other_scope, other_key, other_modes)
                or first_pct == second_pct
            ):
                continue
            if scope in exclusive_scopes or any(
                EXCLUSIVE.search(fragments[source]) for source in (scope, a, b)
            ):
                continue
            overlap = max(first, second)
            yield card(
                "contradiction",
                (
                    "При простое более "
                    f"{overlap:f}"
                    " мин одновременно применимы удержан"
                    "ия "
                    f"{first_pct:f}"
                    "% и "
                    f"{second_pct:f}"
                    "%. Сверьте приоритет и порядок сумм"
                    "ирования."
                ),
                scope,
                a,
                b,
            )


def extract(client, fragments, endpoint):
    request = {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(fragments, ensure_ascii=False)},
        ],
        "temperature": 0,
        "seed": 42,
        "max_tokens": 900,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_object", "schema": SCHEMA},
    }
    with client.open(
        Request(
            endpoint,
            data=json.dumps(request).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        ),
        timeout=120,
    ) as response:
        choice = json.load(response)["choices"][0]
    if choice["finish_reason"] != "stop":
        raise ValueError("Incomplete numeric facts")
    return json.loads(choice["message"]["content"])["facts"]


def review(fragments, facts=()):
    """Return grounded cards from an id-to-source-text mapping and optional ML facts."""
    source = ({"fragment_id": identity, "text": text} for identity, text in fragments.items())
    ranges = [
        card(
            "contradiction",
            proposal["reason"],
            *(ref["fragment_id"] for ref in proposal["references"]),
        )
        for proposal in propose_range_boundaries(source)
    ]
    return [*numeral_cards(fragments), *tier_cards(fragments, facts), *ranges]


def literal_tiers(fragments):
    """The rules recognize adjacent list items beneath an explicit withholding clause."""
    scope = None
    for identity, text in fragments.items():
        if DOWNTIME.search(text) and DEDUCTION.search(text) and text.rstrip().endswith(":"):
            scope = identity
        elif scope is not None and text.lstrip().startswith(("-", "–", "—", "•")):
            yield {"fragment_id": identity, "quote": text, "scope_id": scope, "scope_key": scope}
        else:
            scope = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON object mapping stable fragment IDs to text")
    parser.add_argument("--model-url", help="OpenAI-compatible local chat completions endpoint")
    args = parser.parse_args()
    fragments = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if not isinstance(fragments, dict) or any(
        not k.strip() or not isinstance(v, str) or not v.strip() for k, v in fragments.items()
    ):
        parser.error("expected a nonempty text per fragment ID")
    facts = (
        extract(build_opener(ProxyHandler({})), fragments, args.model_url)
        if args.model_url
        else literal_tiers(fragments)
    )
    print(json.dumps(review(fragments, facts), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
