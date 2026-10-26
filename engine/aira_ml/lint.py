"""Линтер формулировок по свойствам ISO/IEC/IEEE 29148 (§5.2.5–5.2.6).

Правила — регулярные выражения, без модели: дёшево и объяснимо.
Полная версия линтера (8 правил, F1 0,86 на 60 размеченных) осталась на маке
в ~/Desktop/стартап/pipeline/req_audit/rules.py — перенести, когда мак будет в сети.

Урок оттуда: границы слова считаем вместе с дефисом, иначе «прост» находится
внутри «Confluence-пространств».
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    code: str
    words: tuple[str, ...]
    severity: str
    property: str
    explanation: str


def _rx(words):
    alt = "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{alt})(?![\w-])", re.IGNORECASE)


RULES = [
    Rule("VAGUE", ("быстро", "быстрый", "быстрая", "удобно", "удобный", "удобная", "эффективно",
                   "оптимально", "оптимальный", "достаточно", "легко", "просто", "гибко",
                   "надёжно", "надежно", "своевременно", "интуитивно", "понятный", "современный",
                   "максимально", "минимально", "высокая производительность", "оперативно"),
         "warning", "проверяемость (verifiable)",
         "Формулировка не проверяема: нельзя составить тест-кейс. Нужна измеримая граница."),
    Rule("ESCAPE", ("по возможности", "при необходимости", "если возможно", "по мере возможности",
                    "в случае необходимости", "как правило"),
         "warning", "однозначность (unambiguous)",
         "Оговорка оставляет выполнение на усмотрение исполнителя."),
    Rule("OPEN_END", ("и т.д.", "и т. д.", "и т.п.", "и т. п.", "и другие", "и прочее", "и др."),
         "warning", "полнота (complete)",
         "Открытый перечень: непонятно, что ещё входит в требование."),
    Rule("AND_OR", ("и/или",), "info", "однозначность (unambiguous)",
         "«и/или» допускает две разные реализации."),
]
_COMPILED = [(r, _rx(r.words)) for r in RULES]

# «Просто» как уточнение («не просто настройка») — не оценка качества
_NOT_PROSTO = re.compile(r"не\s+просто", re.IGNORECASE)


def lint(text):
    """Список (rule, start, end, quote) для одного требования."""
    hits = []
    for rule, rx in _COMPILED:
        for m in rx.finditer(text):
            if m.group(0).lower() == "просто" and _NOT_PROSTO.search(text[max(0, m.start() - 4):m.end()]):
                continue
            hits.append((rule, m.start(), m.end(), m.group(0)))
    return sorted(hits, key=lambda h: h[1])
