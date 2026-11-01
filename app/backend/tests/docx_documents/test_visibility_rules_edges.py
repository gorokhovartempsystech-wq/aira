"""Batch work bounds, source consistency and unresolved selector precedence."""

from hashlib import sha256

import pytest
from test_docx_visibility_rules import query, resolve, source
from test_docx_visibility_styles import fixture, style

from ara.docx_analysis.visibility import StyleContextError, StyleContextLimits, rules


def test_ten_thousand_queries_read_the_pinned_catalog_once(monkeypatch):
    original = rules.read_style_context
    calls = []

    def counted(data, **kwargs):
        calls.append(sha256(data).hexdigest())
        return original(data, **kwargs)

    monkeypatch.setattr(rules, "read_style_context", counted)
    raw = source(False, True)
    before = sha256(raw).hexdigest()
    result = resolve(raw, (query(paragraph_style_id="P"),) * 10000)
    assert calls == [before] and len(result.results) == 10000
    assert all(r.hidden for r in result.results)
    assert sha256(raw).hexdigest() == before


def test_nested_bounds_and_invalid_limits_are_rechecked():
    raw = source()
    bounds = rules.RunVisibilityLimits()
    object.__setattr__(bounds.styles, "max_nodes", True)
    with pytest.raises(rules.RunVisibilityError):
        resolve(raw, (), limits=bounds)
    bounds = rules.RunVisibilityLimits()
    object.__setattr__(bounds, "max_queries", True)
    with pytest.raises(rules.RunVisibilityError):
        resolve(raw, (), limits=bounds)
    with pytest.raises(StyleContextError) as caught:
        resolve(raw, (), limits=rules.RunVisibilityLimits(styles=StyleContextLimits(max_styles=1)))
    assert caught.value.code == "style_limit_exceeded"


@pytest.mark.parametrize("name", ["specVanish", "webHidden"])
def test_non_neutral_default_character_metadata_remains_unresolved(name):
    raw = fixture(
        style("C", "<w:rPr><w:" + name + "/></w:rPr>", kind="character", attrs='w:default="1"')
    )[0]
    result = resolve(
        raw,
        (
            query(direct_vanish=False, direct_spec_vanish=False, direct_web_hidden=False),
            query(character_style_id="C"),
        ),
    )
    assert result.results[0].code == "implicit_character_style"
    assert result.results[1].status == "visible"


def test_paragraph_error_precedes_character_error_and_case_is_exact():
    raw = source()
    result = resolve(
        raw,
        (
            query(paragraph_style_id="missing", character_style_id="missing"),
            query(paragraph_style_id="p"),
            query(character_style_id="c"),
        ),
    )
    assert [r.code for r in result.results] == [
        "missing_paragraph_style",
        "missing_paragraph_style",
        "missing_character_style",
    ]


def test_source_and_catalog_changes_are_visible_even_when_results_equal():
    raw1 = source()
    raw2 = fixture(style("unused"))[0]
    first, second = resolve(raw1, (query(),)), resolve(raw2, (query(),))
    assert first.results == second.results
    assert first.source_sha256 != second.source_sha256
    assert first.context_sha256 != second.context_sha256


def test_default_paragraph_unresolved_cannot_be_overridden_by_direct_false():
    raw = fixture(style("P", '<w:basedOn w:val="missing"/>', attrs='w:default="1"'))[0]
    assert (
        resolve(raw, (query(direct_vanish=False),)).results[0].code == "unresolved_paragraph_style"
    )
