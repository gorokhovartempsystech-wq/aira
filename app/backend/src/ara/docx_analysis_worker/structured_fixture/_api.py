"""Explicit fixture2; structure is input data, never a claim of real inference."""

from hashlib import sha256

from ara.docx_analysis.storage_codec import ExecutionSpec
from ara.docx_analysis.visible_lists._models import PROFILE as LIST_PROFILE
from ara.docx_analysis.visible_main._models import POLICY, PROFILE
from ara.docx_analysis.visible_outline._models import PROFILE as OUTLINE_PROFILE
from ara.docx_analysis.visible_style_lists._models import PROFILE as STYLE_LIST_PROFILE
from ara.docx_analysis.visible_word._models import PROFILE as WORD_PROFILE

from ..review_fixture import ReviewFixtureError, _example, _fragments, _request_header, _require
from ._context import read, read_outline, read_style_lists


def fixture_execution():
    return ExecutionSpec(
        execution_kind="fixture",
        engine_version="0.1.0",
        models_version="aira-review-fixture-2",
        model_sha256=sha256(b"aira-review-fixture-model/2").hexdigest(),
        adapter_sha256=sha256(b"aira-review-fixture-adapter/2").hexdigest(),
    )


def _reply(request):
    execution, body = _request_header(request, fixture_execution())
    _require(body["policy_version"] == POLICY)
    pair = body["schema_version"], body["profile"]
    engine = body["engine_request"]
    if pair == ("docx-review/1", PROFILE):
        fragments = _fragments(engine)
        selected, list_count, note_count = None, 0, 0
    else:
        _require(
            pair
            in (
                ("docx-review/2", LIST_PROFILE),
                ("docx-review/3", OUTLINE_PROFILE),
                ("docx-review/4", STYLE_LIST_PROFILE),
                ("docx-review/5", WORD_PROFILE),
            )
        )
        reader = (
            read
            if pair[0] == "docx-review/2"
            else read_outline
            if pair[0] == "docx-review/3"
            else read_style_lists
        )
        fragments = _fragments(engine, keys="fragments disabled_types dismissed document_context")
        selected, list_count, note_count = reader(
            engine["document_context"], fragments, body["source"]["source_sha256"]
        )
    first, label = selected if selected is not None else (fragments[0], None)
    explanation = "Учебный пример замечания AIRA. Реальная модель не запускалась."
    if label is not None:
        explanation += " Пункт списка: «" + label[:64] + "»."
    explanation += f" Пунктов списков: {list_count}. Связей со сносками: {note_count}."
    return _example(execution, first, len(fragments), explanation=explanation)


def reply_for(request):
    try:
        return _reply(request)
    except Exception:
        raise ReviewFixtureError() from None
