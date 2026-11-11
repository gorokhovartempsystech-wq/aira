"""Find competing repeat inspection schedules with explicit common scope."""
from collections import defaultdict
import re

from .aira_numeric_review import card
from .measurement_gaps import ROW, has


OBJECT = r"[А-ЯЁ]{2,8}(?:-[А-ЯЁ]{1,8})?"
PROSE_OBJECT = re.compile(rf"^\s*(?P<names>{OBJECT}(?:\s*,\s*{OBJECT})*)\s*[-–—:]")
TABLE_OBJECT = re.compile(rf"(?i:акт\w*\s+испытани\w*\s+)(?P<name>{OBJECT})\b")
INITIAL = r"первичн\w*\s+обследовани"
ON_REQUEST = r"далее\s+(?:только\s+)?по\s+заявк"
SEPARATE_PAYMENT = r"оплачива\w*\s+отдельно|отдельн\w*\s+оплат"
PERIOD = r"далее\s+не\s+реже\s+(?:одного\s+)?раза\s+в\s+(?:\d+\s+)?(?:день|дн\w*|недел\w*|месяц\w*|квартал\w*|год\w*)"


def review(units):
    prose = defaultdict(list)
    table = defaultdict(list)
    resolved = set()
    in_inspection_list = False
    for unit in units:
        text = unit["text"]
        if has(text, r"планов\w*\s+испытани", r"по\s+заявк", SEPARATE_PAYMENT):
            resolved.update(re.findall(rf"\b{OBJECT}\b", text))
        if row := ROW.fullmatch(unit["xml_path"]):
            table[row[1]].append(unit)
            continue
        if has(text, r"испытани\w*", r"работоспособност", r"должн\w+\s+проводиться\s+для\s*:\s*$"):
            in_inspection_list = True
        elif in_inspection_list and (match := PROSE_OBJECT.match(text)):
            if ("," not in match["names"] and has(text, INITIAL, ON_REQUEST, SEPARATE_PAYMENT)
                    and not has(text, r"не\s+реже")):
                prose[match["names"]].append(unit["id"])
        else:
            in_inspection_list = False

    for row in table.values():
        labels = [(unit, match["name"]) for unit in row if (match := TABLE_OBJECT.search(unit["text"]))]
        intervals = [unit for unit in row if has(unit["text"], INITIAL, PERIOD)]
        if len(labels) != 1 or len(intervals) != 1:
            continue
        label, name = labels[0]
        if name in resolved or len(prose[name]) != 1:
            continue
        period = re.search(PERIOD, intervals[0]["text"], re.I).group()
        yield card("contradiction", f"После первичного обследования для {name} указаны испытания по заявкам "
                   f"с отдельной оплатой, а в таблице — «{period}». Сверьте, какие повторные испытания "
                   "обязательны по графику и какие оплачиваются отдельно.", prose[name][0], label["id"], intervals[0]["id"])
