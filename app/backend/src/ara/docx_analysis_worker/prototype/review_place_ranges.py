"""Find a shared boundary that assigns different counts within one stated scale."""
import re

from .compose_verification_slots import compact, references


BAND = re.compile(
    r"\bот\s+(?P<low>\d{1,6})\s+до\s+(?P<high>\d{1,6})"
    r"(?:\s+(?P<unit>(?!(?:включительно|исключительно)\b)[а-яё]+))?\s+(?:включительно\s+)?[-–—:]\s+"
    r"(?P<count>\d{1,6})\s+(?P<label>[а-яё]+(?:\s+(?!(?:и|или|либо)\b)[а-яё]+){0,2})",
    re.I,
)
SEPARATOR = re.compile(r"\s*[,;]\s*")


def same_labels(left, right):
    if len(left) != len(right):
        return False
    for a, b in zip(left, right, strict=True):
        size = min(5, max(3, min(len(a), len(b)) - 1))
        if a[:size] != b[:size]:
            return False
    return True


def propose(fragments):
    for fragment in fragments:
        text = compact(fragment["text"]).casefold()
        bands = list(BAND.finditer(text))
        for first, second in zip(bands, bands[1:]):
            if not SEPARATOR.fullmatch(text[first.end():second.start()]):
                continue
            boundary = first["high"]
            if not (int(first["low"]) < int(boundary) == int(second["low"]) < int(second["high"])):
                continue
            if first["unit"] and second["unit"] and first["unit"] != second["unit"]:
                continue
            if int(first["count"]) == int(second["count"]) or not same_labels(first["label"].split(), second["label"].split()):
                continue
            reason = (f"Граница {boundary} указана в двух соседних диапазонах с разными значениями "
                      f"({first['count']} и {second['count']}). Сверьте, какое значение действует на границе.")
            yield {"slot": "range_boundary", "text": "Разные значения на общей границе диапазонов",
                   "reason": reason, "references": references(fragment)}
