"""Synthetic source-bound acceptance for PR29 integration repairs."""

import json
from xml.etree import ElementTree as ET

import pytest
from test_docx_review_v1 import provenance
from test_docx_visible_word import W, alter, build, source
from test_local_model_adapter import raw

from ara.docx_analysis.word_review import prepare_word_review, validate_word_reply
from ara.docx_analysis_worker.local_model import adapt
from ara.docx_analysis_worker.prototype import propose
from ara.docx_analysis_worker.prototype.aira_review import review


def document(texts):
    def change(xml):
        body = xml.find(W + "body")
        for paragraph in list(body.findall(W + "p")):
            body.remove(paragraph)
        for i, text in enumerate(texts):
            paragraph = ET.Element(W + "p")
            ET.SubElement(ET.SubElement(paragraph, W + "r"), W + "t").text = text
            body.insert(i, paragraph)

    data = alter(source("plain"), "word/document.xml", change)
    snapshot = build(data)
    assert snapshot.complete
    return data, snapshot


def validate(texts):
    data, snapshot = document(texts)
    prov = provenance(models_version="0.2m")
    request = prepare_word_review(data, snapshot, provenance=prov)
    fragments = json.loads(request.engine_request_json)["fragments"]
    cards = propose(fragments)
    engine = raw()
    engine["checked"] = dict(
        fragments=len(fragments), active=len(fragments), skipped_status=0, pairwise=0
    )
    envelope = validate_word_reply(
        data, snapshot, provenance=prov, request=request, reply=adapt(engine, questions=cards)
    )
    return cards, json.loads(envelope.wire_json), snapshot


@pytest.mark.parametrize("count", [1, 6, 8, 20])
def test_every_independent_card_reaches_validated_word_result(count):
    cards, result, _ = validate(["Срок поставки составляет 10 (двадцать) дней."] * count)
    assert len(cards) == len(result["standalone_questions"]) == count
    assert result["counts"]["questions"] == count


def test_numeric_anchor_selects_error_after_long_prefix_and_emoji():
    text = "События 😀 регистрируются. " * 40 + "Срок поставки составляет 10 (двадцать) дней."
    cards, result, _ = validate([text])
    reference = cards[0]["references"][0]
    evidence = result["standalone_questions"][0]["evidence"][0]
    assert reference["start"] > 500
    assert evidence["quote"] == text[reference["start"] : reference["end"]] == "10 (двадцать) дней"


@pytest.mark.parametrize("count", [16, 17, 33])
def test_reference_parts_retain_all_sources_with_existing_contract(count):
    cards, result, snapshot = validate(
        [f"Участок {i}: требуется акт освидетельствования скрытых работ." for i in range(count)]
    )
    assert len(cards) == (count + 15) // 16
    assert all(1 <= len(card["references"]) <= 16 for card in cards)
    assert {ref["fragment_id"] for card in cards for ref in card["references"]} == {
        fragment.fragment_id for fragment in snapshot.fragments
    }
    assert len(result["standalone_questions"]) == len(cards)
    if count > 16:
        assert all("часть" in card["text"] for card in cards)


def test_fallback_cites_whole_paragraph_not_arbitrary_prefix():
    text = "Общее описание системы. " * 35 + "Доступность системы должна составлять 99,9%."
    _, result, _ = validate([text])
    assert any(q["evidence"][0]["quote"] == text for q in result["standalone_questions"])


@pytest.mark.parametrize(
    "text",
    [
        "Доступность системы 99,9% не требуется.",
        "Не требуется доступность системы 99,9%.",
        "Срок поставки составляет 10 (десять) дней.",
        (
            "Доступность системы должна составлять 99,9% за календарный м"
            "есяц. Плановые перерывы включаются в расчёт доступности."
        ),
    ],
)
def test_negative_and_fully_specified_controls_have_no_prototype_cards(text):
    assert review({"a": text}) == []


def test_unrelated_negation_does_not_remove_required_availability_question():
    assert review(
        {"a": "Доступность системы должна составлять 99,9%. Отчёт об ошибках не требуется."}
    )
