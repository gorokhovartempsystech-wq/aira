"""Контракт движка: примеры из contracts/examples соответствуют схеме; разбор текста — без моделей."""
import json
from pathlib import Path

import jsonschema

from aira_ml.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
SCHEMA = json.loads((CONTRACTS / "engine.schema.json").read_text(encoding="utf-8"))


def check(obj, name):
    jsonschema.validate(obj, {**SCHEMA, "$ref": f"#/$defs/{name}"})


def load(name):
    return json.loads((CONTRACTS / "examples" / name).read_text(encoding="utf-8"))


def test_examples_match_schema():
    check(load("review.request.json"), "request")
    check(load("impact.request.json"), "request")
    check(load("review.response.json"), "review_response")
    check(load("impact.response.json"), "impact_response")
    check(load("parse.response.json"), "parse_response")


def test_parse_statuses_and_offsets():
    text = ("# Правила\n- Возврат возможен в течение 14 дней с даты получения.\n"
            "# Архив / Правила 2023\n- Возврат возможен в течение 7 дней с даты получения.\n"
            "# Заметки\n- Обсуждается: продлить срок возврата до 30 дней.\n")
    frags = Engine.parse_text(text, "Возвраты")
    check({"fragments": frags}, "parse_response")
    assert [f["status"] for f in frags] == ["active", "deprecated", "discussion"]
    for f in frags:
        assert text[f["offset"]:f["offset"] + len(f["text"])] == f["text"]


def test_changed_terms_prefers_numbers():
    assert Engine.changed_terms("Срок — 14 дней с даты получения.", "Срок — 30 дней с даты получения.") == ["14"]
