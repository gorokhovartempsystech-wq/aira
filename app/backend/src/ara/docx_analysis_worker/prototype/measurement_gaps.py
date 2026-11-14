"""Find missing measurement conditions in paragraphs and literal Word table rows."""

import re
from collections import defaultdict
from dataclasses import dataclass

from .compose_verification_slots import compact, references

ROW = re.compile(r"(.*/tr\[\d+\])/tc\[\d+\]/p\[\d+\]$")
PERCENT = r"\d+(?:[.,]\d+)?\s*%"
PERIOD = (
    "ежемесяч\\w*|ежекварталь\\w*|ежегод\\w*|(?:за|в)\\s+(?:(?:\\d+|к"
    "алендарн\\w+)\\s+)?(?:месяц\\w*|квартал\\w*|год\\w*|дн\\w*)"
)
MAINTENANCE = (
    "(?:планов\\w+|согласованн\\w+)\\s+(?:перерыв|останов|просто|сер"
    "висн\\w+\\s+окн)|профилактич\\w+\\s+(?:перерыв|работ)"
)
ACCOUNTING = r"(?:не\s+)?(?:учитыва|включа|исключа|вычита)\w*"
PEAK = r"пиков\w+\s+нагруз|нагрузочн\w+\s+(?:тест|испытан)|нагрузк\w+,?\s+близк\w+\s+к\s+продуктив"
PEAK_WINDOW = r"конец\s+месяца|в конце\s+месяца|конец\s+квартала|в конце\s+квартала"
VOLUME = (
    "\\d[\\d ]*\\s*(?:rps|tps|одновременн\\w+\\s+(?:пользовател|сесси"
    "|клиент)|(?:запрос|операц|документ|сообщен|код|звонк)\\w*\\s*("
    "?:/|в\\s+)(?:секунд|минут)\\w*)"
)
MIX = (
    "(?:профил|смес|дол|соотношени|распределен|состав|перечен)\\w*"
    "\\s+(?:тестов\\w+\\s+)?(?:операц|документ|запрос|сценари|сообще"
    "н)\\w*"
)
TARGET = r"не\s+(?:более|дольше|выше)\s+\d+(?:[.,]\d+)?\s*(?:мс|секунд|минут|час)|\bp(?:90|95|99)\b"
ROLLOUT = (
    "обновлен\\w*|переключен\\w*|переход\\w*\\s+на\\s+нов\\w+|внедрен"
    "\\w*\\s+(?:нов\\w+\\s+)?верси|работ\\w*\\s+на\\s+продуктив"
)
VERSION_CHANGE = r"переход\w*\s+на\s+нов\w+\s+верси|(?:обновлен|обновит)\w*\s+конфигурац"
PRODUCTION = r"продуктив\w*|промышленн\w*|рабоч\w+\s+(?:систем|контур|баз)"
DOWNTIME = r"прост(?:ой|оя|ое)|остановк\w+|недоступност\w*|перерыв\w*"
TIME = r"\d+(?:[.,]\d+)?\s*(?:(?:рабоч|календарн)\w+\s+)?(?:секунд|минут|час|дн|сут)\w*"
TRIGGER = (
    "(?:при|если|в случае)\\s+(?:превышен|неуспеш|отказ|сбо|ошиб|н"
    "есоответств)|(?:услови|триггер|критери)\\w*\\s+(?:начала\\s+)?о"
    "тката"
)
AVAILABILITY = r"доступност\w*|\buptime\b"
REPLACEMENT = r"замен\w+\s+(?:критичн\w+\s+)?(?:компонент|детал|модул|узл|оборудован)"
SLA_RESOLUTION = (
    r"врем\w+\s+решени\w+\s+(?:заяв|инцидент)|срок\w*\s+(?:решени|устранени)\w+\s+(?:заяв|инцидент)"
)
CLOCK_START = r"с момента|с даты|с отметки|начина\w+\s+(?:с|при)|отсчитыва\w+\s+(?:с|от)"
CLOCK_END = (
    "до (?:фактическ\\w+\\s+)?(?:замен|установ|восстановл|закрыти|р"
    "ешени)|подтвержда\\w+\\s+(?:актом|записью|отметкой)"
)
CLOCK_PAUSE = (
    "сч[её]тчик\\w*\\s+(?:останавлива|приостанавлива)|(?:врем\\w+|пе"
    "риод\\w*)\\s+ожидани\\w+\\s+.{0,30}(?:исключа|не учитыва)"
)
COMPUTE_THROUGHPUT = (
    r"\d[\d ]*\s+(?:страниц|кадр|документ)\w*\s+(?:за|в)\s+(?:час|минут|секунд)\w*\s+на\s+ядр\w*"
)
HARDWARE = r"(?:модел|конфигурац|тип)\w*\s+(?:cpu|процессор)|\b(?:intel|amd|arm|xeon|epyc)\b"
INPUT_MIX = (
    r"(?:набор|профил|состав|распределен)\w*\s+(?:входн\w+\s+)?(?:страниц|документ|изображени|кадр)"
)


@dataclass(frozen=True)
class Evidence:
    text: str
    fragments: tuple


def evidence_blocks(fragments):
    """Keep different rows and unrelated paragraphs apart."""
    rows = defaultdict(list)
    for fragment in fragments:
        match = ROW.fullmatch(fragment["xml_path"])
        if match:
            rows[match.group(1)].append(fragment)
    for fragment in fragments:
        yield Evidence(compact(fragment["text"]), (fragment,))
    for fragments_in_row in rows.values():
        if 2 <= len(fragments_in_row) <= 8:
            yield Evidence(
                " ".join(compact(item["text"]) for item in fragments_in_row),
                tuple(fragments_in_row),
            )


def has(text, *patterns):
    return all(re.search(pattern, text, re.I) for pattern in patterns)


def availability_proof(text, field, metric):
    if not has(text, AVAILABILITY):
        return False
    percentages = re.findall(PERCENT, text)
    if percentages and metric.replace(",", ".") not in {
        compact(x).replace(" ", "").replace(",", ".") for x in percentages
    }:
        return False
    if field == "period":
        return has(text, PERIOD)
    return has(text, ACCOUNTING, MAINTENANCE)


def field_proof(slot, card, text):
    if slot == "availability_fields":
        return [
            field for field in card["fields"] if availability_proof(text, field, card["metric"])
        ]
    if slot == "peak_test_profile":
        return ["profile"] if has(text, PEAK, VOLUME, MIX) else []
    if slot == "performance_profile":
        return ["profile"] if has(text, VOLUME, MIX) else []
    if slot == "throughput_bench":
        return ["profile"] if has(text, COMPUTE_THROUGHPUT, HARDWARE, INPUT_MIX) else []
    if slot == "production_change":
        found = []
        if has(text, ROLLOUT, DOWNTIME, TIME, r"максимальн|допустим|не более|не дольше"):
            found.append("downtime")
        if has(text, ROLLOUT, r"откат", TRIGGER) and not has(
            text, r"при необходимост|по необходимост"
        ):
            found.append("rollback")
        return found
    if slot in {"replacement_clock", "resolution_clock"}:
        replacement = slot == "replacement_clock"
        topic = REPLACEMENT if replacement else SLA_RESOLUTION
        if not has(text, topic):
            return []
        fields = []
        if has(text, CLOCK_START):
            fields.append("start")
        if has(text, CLOCK_END if replacement else CLOCK_PAUSE):
            fields.append("end" if replacement else "pause")
        return fields
    raise ValueError(f"Unknown measurement slot: {slot}")


def drafts(fragments):
    proposals = {}

    def offer(slot, draft, priority=0):
        if slot not in proposals or priority > proposals[slot][0]:
            proposals[slot] = (priority, draft)

    for block in evidence_blocks(fragments):
        text = block.text
        percentage = re.search(PERCENT, text, re.I)
        if percentage and has(
            text, AVAILABILITY, r"\b(?:SLA|uptime)\b|платформ|сервис|систем|^доступность"
        ):
            metric = percentage.group().replace(" ", "")
            fields = [
                name
                for name in ("period", "maintenance")
                if not availability_proof(text, name, metric)
            ]
            if fields:
                offer(
                    "availability_fields",
                    {
                        "metric": metric,
                        "fields": fields,
                        "references": references(*block.fragments),
                    },
                    priority=int(len(block.fragments) > 1 and len(text) <= 65),
                )

        if has(text, PEAK) and has(text, r"тест|испытан|эксплуатац|пиков\w+\s+нагруз"):
            if not has(text, VOLUME, MIX):
                window = re.search(PEAK_WINDOW, text, re.I)
                acceptance = has(text, r"при[её]мк|при[её]моч")
                offer(
                    "peak_test_profile",
                    {
                        "fields": ["profile"],
                        "references": references(*block.fragments),
                        "window": window.group() if window else None,
                        "documents": has(text, r"документ\w+\s+(?:ежемесяч|в месяц)"),
                        "acceptance": acceptance,
                    },
                    priority=2 if window else int(acceptance),
                )

        if has(
            text,
            r"отклик|врем\w+\s+ответ|пропускн\w+\s+способност|деградац\w+\s+производительност",
            r"нагруз|\brps\b|одновременн",
        ) and has(text, TARGET):
            if not has(text, VOLUME, MIX):
                offer(
                    "performance_profile",
                    {"fields": ["profile"], "references": references(*block.fragments)},
                )

        if has(text, COMPUTE_THROUGHPUT) and not has(text, HARDWARE, INPUT_MIX):
            offer(
                "throughput_bench",
                {"fields": ["profile"], "references": references(*block.fragments)},
            )

        explicit_version = has(text, VERSION_CHANGE)
        production_window = has(
            text, ROLLOUT, PRODUCTION, DOWNTIME + r"|откат|технологическ\w+\s+окн"
        )
        if explicit_version or production_window:
            present = field_proof("production_change", {}, text)
            fields = [name for name in ("downtime", "rollback") if name not in present]
            if fields:
                offer(
                    "production_change",
                    {
                        "fields": fields,
                        "references": references(*block.fragments),
                        "version_change": explicit_version,
                    },
                    priority=int(production_window),
                )
        for slot, topic, second_field in (
            ("replacement_clock", REPLACEMENT, "end"),
            ("resolution_clock", SLA_RESOLUTION, "pause"),
        ):
            duration = re.search(TIME, text, re.I)
            if duration and has(text, topic, r"не более|предельн|норматив|максимальн"):
                found = field_proof(slot, {}, text)
                fields = [field for field in ("start", second_field) if field not in found]
                if fields:
                    offer(
                        slot,
                        {
                            "fields": fields,
                            "duration": duration.group(),
                            "references": references(*block.fragments),
                        },
                    )
    return {slot: draft for slot, (_, draft) in proposals.items()}


def render(slot, card, remaining):
    if slot == "availability_fields":
        metric = card["metric"]
        if remaining == ["period", "maintenance"]:
            text = (
                "За какой период измеряют доступност"
                "ь "
                f"{metric}"
                " и входят ли в расчёт согласованные"
                " перерывы?"
            )
        elif remaining == ["period"]:
            text = f"За какой расчётный период проверяют доступность {metric}?"
        else:
            text = f"Включаются ли согласованные перерывы в расчёт доступности {metric}?"
        reason = "Числовой показатель требует однозначного правила расчёта."
    elif slot == "peak_test_profile":
        if card["window"] and card["documents"]:
            window = re.sub(r"^в конце", "конец", card["window"], flags=re.I)
            text = (
                "Какой поток и состав документов нуж"
                "но воспроизвести в нагрузочном испы"
                "тании для пика ("
                f"{window}"
                ")?"
            )
        elif card["acceptance"]:
            text = (
                "Какой профиль нагрузки нужно воспроизвести при приёмочном ис"
                "пытании и по каким числовым критериям оно считается успешным"
                "?"
            )
        else:
            text = (
                "Какой пиковый темп и состав операций нужно воспроизвести при"
                " нагрузочном испытании?"
            )
        reason = "Для испытания нужен воспроизводимый профиль пиковой нагрузки."
    elif slot == "performance_profile":
        text = (
            "При какой интенсивности и смеси операций проверяют указанный"
            " предел времени ответа или производительности?"
        )
        reason = "Для проверки числовой границы необходимо задать нагрузку."
    elif slot == "throughput_bench":
        text = (
            "Какую конфигурацию процессора и какой состав входных материа"
            "лов используют при проверке указанной пропускной способности"
            " на ядро?"
        )
        reason = (
            "Измерение на ядро зависит от испытательной конфигурации и контрольных входных данных."
        )
    elif slot == "production_change":
        change = (
            "при переходе на новую версию системы"
            if card["version_change"]
            else "при изменении рабочей системы"
        )
        if remaining == ["downtime", "rollback"]:
            text = (
                "Какой максимальный простой допустим"
                " "
                f"{change}"
                " и при каком результате начинается "
                "откат?"
            )
        elif remaining == ["downtime"]:
            text = f"Какой максимальный простой допустим {change}?"
        else:
            text = f"При каком результате требуется начать откат {change}?"
        reason = "Для безопасного изменения рабочей системы нужны проверяемые условия выполнения."
    elif slot == "replacement_clock":
        duration = card["duration"]
        if remaining == ["start", "end"]:
            text = (
                "С какого события отсчитывается срок"
                " замены компонента ("
                f"{duration}"
                ") и каким событием подтверждается с"
                "облюдение срока?"
            )
        elif remaining == ["start"]:
            text = f"С какого события отсчитывается срок замены компонента ({duration})?"
        else:
            text = f"Каким событием подтверждается соблюдение срока замены компонента ({duration})?"
        reason = "Для контроля срока замены нужны определённые границы измерения."
    elif slot == "resolution_clock":
        if remaining == ["start", "pause"]:
            text = (
                "С какого события отсчитывается норматив решения заявки и при"
                " каких ожиданиях приостанавливается отсчёт?"
            )
        elif remaining == ["start"]:
            text = "С какого события отсчитывается норматив решения заявки?"
        else:
            text = "При каких ожиданиях приостанавливается отсчёт норматива решения заявки?"
        reason = "Указанные сроки решения требуют единого способа измерения."
    else:
        raise ValueError(f"Unknown measurement slot: {slot}")
    return {"text": text, "reason": reason, "references": card["references"]}
