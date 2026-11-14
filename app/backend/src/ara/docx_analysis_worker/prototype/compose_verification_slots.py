"""Compose source-linked questions for missing verification fields."""

import argparse
import json
import re
from pathlib import Path

TIME = r"\d+\s*(?:р\.\s*д\.|рабоч\w+\s+(?:дн\w*|час\w*)|час\w*|дн\w*|минут\w*|сут\w*)"
START = r"\b(?:с момента|с даты|после подписан|после получен|от даты|с дня)\b"
SCOPE = re.compile(r"^срок[аи]?\s+(поставки|передачи|выполнения|оказания|доставки)\b", re.I)
CONDITION = re.compile(
    (
        "\\bпри (?:полном )?совпадении ([а-яё-]+(?:\\s+[а-яё-]+){0,2})\\"
        "s+([А-ЯЁ][а-яё]+|[а-яё]+\\s+(?:передает|отправляет))"
    ),
    re.I,
)
AUDIT = re.compile(r"^журнал\s+(действий\s+[\w-]+(?:\s+[\w-]+)?)\s*[.;]?$", re.I)
RATE = re.compile(r"\b(\d[\d\s\u00a0]{1,9})\s*([мгк]бит/с|rps|tps)\b", re.I)
PERFORMANCE = re.compile(
    r"\b(?:пиков\w+\s+нагрузк|нагрузочн\w+\s+тест|нагрузочн\w+\s+испытан)", re.I
)
MONTHLY = re.compile(r"\d[\d\s\u00a0]{1,12}\s+(?:сообщен|запрос|операц)\w*\s+в месяц", re.I)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def compact(text):
    return " ".join(text.split())


def references(*fragments):
    return [
        {"fragment_id": item["fragment_id"], "start": 0, "end": len(item["text"])}
        for item in fragments
    ]


def same_block(first, second):
    row = r"(.*/tr\[\d+\])/"
    a, b = (re.match(row, fragment["xml_path"]) for fragment in (first, second))
    if a or b:
        return a is not None and b is not None and a.group(1) == b.group(1)
    parent_a, parent_b = (fragment["xml_path"].rsplit("/", 1)[0] for fragment in (first, second))
    return parent_a == parent_b


def drafts(source):
    fragments = source["fragments"]
    text = [compact(f["text"]) for f in fragments]
    results = {}

    def propose(slot, question, reason, *evidence):
        results.setdefault(
            slot, {"text": question, "reason": reason, "references": references(*evidence)}
        )

    for index, (fragment, value) in enumerate(zip(fragments, text, strict=True)):
        label = SCOPE.match(value)
        if label and index + 1 < len(text) and same_block(fragment, fragments[index + 1]):
            following = text[index + 1]
            if re.fullmatch(TIME + r"[ .]*", following, re.I) and not re.search(START, value, re.I):
                propose(
                    "deadline_start",
                    f"От какого события отсчитывается срок {label.group(1)} ({following})?",
                    "Срок указан числом. Для его проверки требуется начало отсчёта.",
                    fragment,
                    fragments[index + 1],
                )

        condition = CONDITION.search(value)
        if condition:
            subject = condition.group(1).split()[0].lower()
            if subject and not any(
                re.search(rf"несовпадени\w*\s+{re.escape(subject)}", line, re.I) for line in text
            ):
                propose(
                    "unmatched_branch",
                    (
                        "Что получает вызывающая сторона и ч"
                        "то должен сделать пользователь при "
                        "несовпадении "
                        f"{subject}"
                        "?"
                    ),
                    (
                        "Описан положительный результат проверки. Для приёмки нужна в"
                        "етка несовпадения."
                    ),
                    fragment,
                )

        if re.fullmatch(r"стандартн\w+\s+гаранти\w+[.;]?", value, re.I):
            propose(
                "warranty_scope",
                "Какой срок действует для стандартной гарантии и какие дефекты она покрывает?",
                "Ссылка на стандартную гарантию оставляет срок и покрытие открытыми.",
                fragment,
            )

        journal = AUDIT.fullmatch(value)
        if journal and not any(
            re.search(r"\b(?:хран|retention)\w*.{0,55}" + TIME, line, re.I)
            and "журнал" in line.lower()
            for line in text
        ):
            propose(
                "audit_retention",
                (
                    "Какой минимальный срок хранения зап"
                    "исей журнала "
                    f"{journal.group(1).lower()}"
                    " требуется?"
                ),
                "Для предусмотренного журнала нужно знать период, доступный для проверки.",
                fragment,
            )

        if PERFORMANCE.search(value):
            monthly = MONTHLY.search(value)
            if monthly:
                propose(
                    "load_peak",
                    (
                        "Какой пиковый темп отправки нужно в"
                        "оспроизвести при нагрузочном тесте,"
                        " если объём составляет "
                        f"{monthly.group(0)}"
                        "?"
                    ),
                    "Месячная ёмкость задана. Тест требует измеримого пикового темпа.",
                    fragment,
                )
            elif re.search(r"при[её]моч\w+\s+тестирован", value, re.I) and not any(
                re.search(r"\d+\s*(?:rps|tps|одновременн\w+\s+(?:пользовател|сесси))", line, re.I)
                for line in text
            ):
                propose(
                    "load_acceptance",
                    (
                        "При каком количестве параллельных сессий или каком темпе зап"
                        "росов проводить приёмочное нагрузочное тестирование?"
                    ),
                    "Нагрузочное испытание предусмотрено. Нужен воспроизводимый профиль нагрузки.",
                    fragment,
                )

        if RATE.search(value) and re.search(r"\bлини\w+,\s+соединяющ\w+\s+", value, re.I):
            clause = re.split(r"(?<=[.!?])\s+", value)
            target = next(
                (part for part in clause if re.search(r"\bлини\w+,\s+соединяющ", part, re.I)), ""
            )
            rate = RATE.search(target)
            if rate:
                propose(
                    "capacity_test",
                    (
                        "Каким измерением подтверждают пропу"
                        "скную способность "
                        f"{compact(rate.group(0))}"
                        " на соединяющих линиях?"
                    ),
                    "Числовое требование задано. Для приёмки нужен метод измерения.",
                    fragment,
                )

        if re.search(r"согласовани\w+\s+и\s+корректировк\w+", value, re.I) and re.search(
            r"промежуточн\w+\s+результат", value, re.I
        ):
            propose(
                "approval_window",
                (
                    "Кто со стороны заказчика и в какой срок согласует промежуточ"
                    "ные результаты и замечания к ним?"
                ),
                (
                    "Предусмотрено согласование промежуточных результатов. Нужны "
                    "ответственный и срок обратной связи."
                ),
                fragment,
            )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshots", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    for path in sorted(args.snapshots.glob("*.json")):
        source = read(path)
        cards = drafts(source) if source["complete"] else {}
        row = {
            "family": source["family"],
            "sha256": source["sha256"],
            "slots": list(cards),
            "arms": {"before_search": list(cards.values())},
        }
        (args.output / path.name).write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(source["family"], list(cards))


if __name__ == "__main__":
    main()
