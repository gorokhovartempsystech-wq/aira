"""Pinned engine0.1 reply syntax without trusting its span or coverage claims."""

import math
import re

from ara.docx_analysis.visible_main import VisibleSpanRequest

from ._models import budget, require, text


def keys(value, expected):
    require(type(value) is dict and set(value) == set(expected.split()))


def number(value, minimum, maximum):
    require(type(value) in (int, float) and minimum <= value <= maximum and math.isfinite(value))


def parse_reply(raw, provenance, limits):
    keys(raw, "engine models issues questions checked seconds")
    require(
        raw["engine"] == provenance.engine_version and raw["models"] == provenance.models_version
    )
    number(raw["seconds"], 0, 300)
    keys(raw["checked"], "fragments active skipped_status")
    require(all(type(v) is int and v >= 0 for v in raw["checked"].values()))
    require(type(raw["issues"]) is list and type(raw["questions"]) is list)
    budget(len(raw["issues"]), limits.max_issues)
    budget(len(raw["questions"]), limits.max_questions)
    questions = [text(q, limits.max_metadata_characters) for q in raw["questions"]]
    require(len(set(questions)) == len(questions))
    issues, requests, ids = [], [], set()
    for original in raw["issues"]:
        keys(
            original,
            "id type severity light confidence fragment_id span related "
            "explanation rule suggestion question",
        )
        item = original.copy()
        identity = text(item["id"], 14)
        require(re.fullmatch(r"iss-[0-9a-f]{10}", identity) is not None and identity not in ids)
        ids.add(identity)
        for field, allowed in (
            ("type", ("formulation", "duplicate", "contradiction")),
            ("severity", ("info", "warning", "critical")),
            ("light", ("red", "yellow")),
        ):
            require(type(item[field]) is str and item[field] in allowed)
        number(item["confidence"], 0, 1)
        text(item["explanation"], limits.max_metadata_characters)
        if item["rule"] is not None:
            text(item["rule"], limits.max_metadata_characters)
        if item["question"] is not None:
            text(item["question"], limits.max_metadata_characters, empty=True)
        item["question"] = item["question"] or None
        text(item["fragment_id"], 128)
        span = item["span"]
        keys(span, "start end quote")
        require(type(span["start"]) is int and type(span["end"]) is int)
        text(span["quote"], limits.view.max_text_characters, empty=True)
        requests.append(
            VisibleSpanRequest(item["fragment_id"], span["start"], span["end"], span["quote"])
        )
        related = item["related"]
        if item["type"] == "formulation":
            require(related is None)
        else:
            keys(related, "fragment_id quote status")
            require(related["status"] == "active")
            text(related["fragment_id"], 128)
            require(related["fragment_id"] != item["fragment_id"])
            text(related["quote"], limits.view.max_text_characters, empty=True)
            requests.append(
                VisibleSpanRequest(
                    related["fragment_id"], 0, len(related["quote"]), related["quote"]
                )
            )
        suggestion = item["suggestion"]
        if suggestion is not None:
            keys(suggestion, "before after")
            for n in ("before", "after"):
                text(suggestion[n], limits.max_suggestion_characters, empty=True)
            require(suggestion["before"] == span["quote"])
        issues.append(item)
    require(set(questions) == {i["question"] for i in issues if i["question"]})
    return issues, tuple(requests)
