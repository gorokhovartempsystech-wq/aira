"""Additional context admission and graph resource regressions."""

from hashlib import sha256

import pytest
from docx_projection_fixtures import package
from test_docx_visibility_styles import MIME, R, W, by_id, fixture, read, style

from ara.docx_analysis.visibility import StyleContextError, StyleContextLimits, read_style_context
from ara.docx_package import DocxError


def test_many_styles_share_provenance_without_copying_ancestor_chains():
    content = style("root", '<w:rPr><w:vanish w:val="0"/></w:rPr>')
    content += "".join(style(f"child{i}", '<w:basedOn w:val="root"/>') for i in range(3000))
    result = read(fixture(content)[0])
    root = by_id(result)["root"].properties.vanish
    assert len(result.styles) == 3001
    assert all(s.properties.vanish == root and s.issues == () for s in result.styles)


def test_chain_budget_applies_after_memoized_parent_with_own_direct_value():
    content = style("A", "<w:rPr><w:vanish/></w:rPr>")
    content += style("B", '<w:basedOn w:val="A"/><w:rPr><w:vanish w:val="0"/></w:rPr>')
    content += style("C", '<w:basedOn w:val="B"/><w:rPr><w:vanish/></w:rPr>')
    raw = fixture(content)[0]
    assert by_id(read(raw, limits=StyleContextLimits(max_chain_depth=3)))[
        "C"
    ].properties.vanish.value
    with pytest.raises(StyleContextError, match="technical limit"):
        read(raw, limits=StyleContextLimits(max_chain_depth=2))


def test_limits_are_revalidated_at_api_entry():
    raw = fixture(style())[0]
    limits = StyleContextLimits()
    object.__setattr__(limits, "max_nodes", True)
    with pytest.raises(StyleContextError) as caught:
        read(raw, limits=limits)
    assert caught.value.code == "invalid_input"


@pytest.mark.parametrize(
    "wrapper",
    [
        '<!DOCTYPE w:styles [<!ENTITY secret "private">]>',
        '<!DOCTYPE w:styles SYSTEM "https://example.invalid/no-fetch">',
    ],
)
def test_dtd_or_entity_in_styles_never_reaches_semantic_reader(wrapper):
    xml = (wrapper + f'<w:styles xmlns:w="{W}"/>').encode()
    raw = package(
        "<w:p/>",
        extra_parts={"word/styles.xml": xml},
        extra_types={"word/styles.xml": MIME},
        links=[{"Id": "s", "Type": R + "styles", "Target": "styles.xml"}],
    )[0]
    with pytest.raises(DocxError) as caught:
        read_style_context(raw, source_sha256=sha256(raw).hexdigest())
    assert caught.value.code == "invalid_package"


def test_case_sensitive_ids_and_metadata_do_not_introduce_inheritance():
    raw = fixture(
        style("Case", "<w:rPr><w:vanish/></w:rPr>")
        + style("case", '<w:link w:val="Case"/><w:next w:val="Case"/>')
        + style(" spaced ", '<w:basedOn w:val="Case"/>')
    )[0]
    records = by_id(read(raw))
    assert records["case"].properties.vanish.value is None
    assert records[" spaced "].properties.vanish.value is True


@pytest.mark.parametrize(
    "content,code",
    [
        ("<w:docDefaults/><w:docDefaults/>" + style(), "unsupported_style_structure"),
        (
            "<w:docDefaults><w:pPrDefault><w:pPr><w:numPr/></w:pPr></w:pPrDefault>"
            "</w:docDefaults>" + style(),
            "unsupported_defaults",
        ),
        (
            style("A", attrs='w:default="1"', kind="table")
            + style("B", attrs='w:default="1"', kind="table"),
            "duplicate_default_style",
        ),
        (style(attrs='w:customStyle="TRUE"'), "invalid_style_identity"),
    ],
)
def test_global_default_and_identity_envelopes(content, code):
    result = read(fixture(content)[0])
    assert result.status == "blocked" and result.issues[0].code == code


def test_own_grammar_failure_wins_over_invalid_parent():
    result = read(fixture(style("A", '<w:basedOn w:val="missing"/><w:unknown/>'))[0])
    assert result.styles[0].issues[0].code == "unsupported_style_structure"


def test_opaque_depth_and_history_tail_budgets_are_not_skipped():
    raw = fixture(style(kind="table", content="<w:a><w:b><w:c/></w:b></w:a>"))[0]
    with pytest.raises(StyleContextError):
        read(raw, limits=StyleContextLimits(max_depth=4))
    raw = fixture(
        style(content='<w:rPr><w:rPrChange w:id="1"><w:rPr/></w:rPrChange>ACTIVE TAIL</w:rPr>')
    )[0]
    record = read(raw).styles[0]
    assert record.properties is None and record.issues[0].code == "unsupported_style_structure"


def test_metadata_decimals_accept_leading_zeroes_without_large_integer_conversion():
    value = "0" * 5000 + "2147483647"
    raw = fixture(
        '<w:latentStyles w:count="'
        + value
        + '"/>'
        + style(content='<w:uiPriority w:val="' + value + '"/>')
    )[0]
    assert read(raw).styles[0].status == "resolved"
    raw = fixture(style(content='<w:uiPriority w:val="2147483648"/>'))[0]
    assert read(raw).styles[0].status == "blocked"
