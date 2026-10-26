"""Классификатор пары «изменение — требование»: противоречие / дубль /
независимые / замена версии.

В эксперименте классификатор зафиксирован, меняется только отбор контекста.

- LLMClassifier — любая OpenAI-совместимая точка входа, temperature 0.
  Включается переменными AIRA_LLM_BASE_URL, AIRA_LLM_MODEL, AIRA_LLM_API_KEY.
- NumericClassifier — без LLM: противоречие = одна тема и разные значения
  в одних единицах («14 дней» против «30 дней»). Узкий, но объяснимый:
  с ним весь конвейер работает без ключей, а ответ честно помечается.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

UNITS = {
    "день": "дни", "дня": "дни", "дней": "дни", "дн": "дни", "сутки": "дни", "суток": "дни",
    "час": "часы", "часа": "часы", "часов": "часы", "ч": "часы",
    "минута": "минуты", "минуты": "минуты", "минут": "минуты", "мин": "минуты",
    "секунда": "секунды", "секунды": "секунды", "секунд": "секунды", "сек": "секунды", "с": "секунды",
    "мс": "мс", "%": "проценты", "процентов": "проценты",
    "мб": "мб", "гб": "гб", "руб": "рубли", "рублей": "рубли", "₽": "рубли",
    "раз": "разы", "раза": "разы", "попытки": "разы", "попыток": "разы",
}
_Q = re.compile(r"(\d+(?:[.,]\d+)?)\s*(" + "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True))
                + r")(?![\w])", re.IGNORECASE)


def quantities(text):
    """[(значение, единица, start, end)]"""
    out = []
    for m in _Q.finditer(text):
        out.append((float(m.group(1).replace(",", ".")), UNITS[m.group(2).lower()], m.start(), m.end()))
    return out


@dataclass
class Verdict:
    relation: str              # contradiction | duplicate | independent | version_update
    confidence: float
    change_quote: str
    candidate_quote: str
    explanation: str


def _sentence(text, pos):
    a = max(text.rfind(".", 0, pos), text.rfind("\n", 0, pos)) + 1
    b = min([i for i in (text.find(".", pos), text.find("\n", pos)) if i != -1] or [len(text)])
    return text[a:b].strip()


class NumericClassifier:
    name = "numeric-heuristic"
    uses_llm = False

    def __init__(self, topic_threshold=0.45, dup_threshold=0.83):
        self.topic = topic_threshold
        self.dup = dup_threshold

    def classify(self, change_text, cand_text, cos, status=None):
        if status == "deprecated":
            return Verdict("version_update", 0.9, "", "", "Второе требование — отменённая версия.")
        if status == "exception":
            return Verdict("independent", 0.6, "", "",
                           "Второе требование — исключение со своей областью действия.")
        qa, qb = quantities(change_text), quantities(cand_text)
        if cos >= self.topic and qa and qb:
            for va, ua, sa, ea in qa:
                for vb, ub, sb, eb in qb:
                    if ua == ub and va != vb:
                        return Verdict("contradiction", round(cos, 3),
                                       _sentence(change_text, sa), _sentence(cand_text, sb),
                                       f"Разные значения одного параметра: {change_text[sa:ea]} и {cand_text[sb:eb]}.")
        if cos >= self.dup:
            return Verdict("duplicate", round(cos, 3), change_text, cand_text,
                           "Требования описывают одно и то же разными словами.")
        return Verdict("independent", round(1 - cos, 3), "", "", "")


PROMPT = """Ты проверяешь требования к ПО. Дано изменённое требование и другое требование из того же проекта.
Определи отношение между ними:
- contradiction — оба действуют одновременно и не могут выполняться вместе;
- duplicate — описывают одно и то же поведение;
- version_update — второе требование — прежняя версия, которую изменение заменяет;
- independent — не влияют друг на друга.
Отвечай только JSON: {{"relation": "...", "change_quote": "...", "candidate_quote": "...", "explanation": "..."}}.
Цитаты — дословные фрагменты, объяснение — одно предложение по-русски.

Изменённое требование:
{change}

Другое требование{status}:
{cand}"""

STATUS_RU = {"active": "действует", "deprecated": "отменено", "exception": "исключение",
             "discussion": "в обсуждении"}


class LLMClassifier:
    uses_llm = True

    def __init__(self, base_url, model, api_key="", timeout=60):
        import httpx
        self.name = f"llm:{model}"
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._client = httpx.Client(timeout=timeout,
                                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {})

    def classify(self, change_text, cand_text, cos, status=None):
        st = f" (статус: {STATUS_RU.get(status, status)})" if status else ""
        body = {"model": self._model, "temperature": 0,
                "messages": [{"role": "user", "content": PROMPT.format(change=change_text, cand=cand_text, status=st)}]}
        r = self._client.post(self._url, json=body)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0)) if m else {}
        rel = d.get("relation", "independent")
        if rel not in ("contradiction", "duplicate", "independent", "version_update"):
            rel = "independent"
        return Verdict(rel, 1.0, d.get("change_quote", ""), d.get("candidate_quote", ""), d.get("explanation", ""))


def default_classifier():
    url, model = os.getenv("AIRA_LLM_BASE_URL"), os.getenv("AIRA_LLM_MODEL")
    if url and model:
        return LLMClassifier(url, model, os.getenv("AIRA_LLM_API_KEY", ""))
    return NumericClassifier()
