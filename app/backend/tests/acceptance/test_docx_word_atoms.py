"""Original evidence for closed font symbols and literal Office Math runs."""

from xml.etree import ElementTree as E

import pytest
from test_docx_move_catalog import resolve
from test_docx_visible_main import source
from test_docx_visible_word import blocked, build, parts

from ara.docx_analysis.visible_word import map_word_span

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def mapped_text(raw, s):
    values = []
    for f in s.fragments:
        span = map_word_span(
            raw, s, fragment_id=f.fragment_id, start=0, end=len(f.text), quote=f.text
        )
        for item in span.slices:
            n = resolve(E.fromstring(parts(raw)[item.anchor.part_name]), item.anchor)
            if item.kind == "symbol":
                assert n.tag.endswith("}sym") and item.start == 0 and item.end == 1
                values.append("✓")
            else:
                values.append(n.text[item.start : item.end])
    return "".join(values)


@pytest.mark.parametrize("hidden", [False, True])
@pytest.mark.parametrize("code", ["F0FC", "f0fc", "00FC"])
def test_known_wingdings_symbol_is_not_private_use_text(hidden, code):
    props = "<w:rPr><w:vanish/></w:rPr>" if hidden else ""
    raw, _ = source(
        "<w:p><w:r><w:t>Done </w:t></w:r><w:r>"
        + props
        + f'<w:sym w:font="Wingdings" w:char="{code}"/></w:r></w:p>'
    )
    s = build(raw)
    assert s.complete and s.analysis_text == ("Done " if hidden else "Done ✓")
    assert mapped_text(raw, s) == s.analysis_text


@pytest.mark.parametrize(
    "atom",
    [
        '<w:sym w:font="Unknown" w:char="F0FC"/>',
        '<w:sym w:font="Wingdings" w:char="F000"/>',
        '<w:sym w:font="Wingdings" w:char="xyz"/>',
        '<w:sym w:char="F0FC"/>',
        '<w:sym w:font="Wingdings" w:char="F0FC"><w:t>lost</w:t></w:sym>',
    ],
)
def test_unknown_symbol_never_guesses_a_letter(atom):
    raw, _ = source("<w:p><w:r><w:t>Check </w:t>" + atom + "</w:r></w:p>")
    blocked(raw)


@pytest.mark.parametrize("hidden", [False, True])
def test_literal_math_keeps_math_text_addresses_and_word_visibility(hidden):
    props = "<w:rPr><w:vanish/></w:rPr>" if hidden else ""
    body = (
        "<w:p><w:r><w:t>Limit </w:t></w:r>"
        + f'<m:oMath xmlns:m="{M}"><m:r><m:rPr><m:sty m:val="p"/></m:rPr>'
        + props
        + "<m:t>x=2😀</m:t></m:r></m:oMath><w:r><w:t> end</w:t></w:r></w:p>"
    )
    raw, _ = source(body)
    s = build(raw)
    assert s.complete and s.analysis_text == ("Limit  end" if hidden else "Limit x=2😀 end")
    assert mapped_text(raw, s) == s.analysis_text


@pytest.mark.parametrize(
    "content",
    [
        "<m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>2</m:t></m:r></m:den></m:f>",
        "<m:r><m:rPr><m:unknown/></m:rPr><m:t>x</m:t></m:r>",
        '<m:r><m:t w:val="wrong">x</m:t></m:r>',
        "<m:r><m:t>x<w:t>lost</w:t></m:t></m:r>",
    ],
)
def test_nonliteral_or_malformed_math_refuses_atomic_analysis(content):
    raw, _ = source(
        "<w:p><w:r><w:t>Check </w:t></w:r>"
        + f'<m:oMath xmlns:m="{M}">'
        + content
        + "</m:oMath></w:p>"
    )
    blocked(raw)


def test_math_inside_field_instruction_is_excluded_but_cached_result_is_read():
    math = f'<m:oMath xmlns:m="{M}"><m:r><m:t>Not a requirement</m:t></m:r></m:oMath>'
    body = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        + math
        + '<w:r><w:fldChar w:fldCharType="separate"/><w:t>Visible result</w:t>'
        + '<w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    raw, _ = source(body)
    s = build(raw)
    assert s.complete and s.analysis_text == "Visible result"
    assert mapped_text(raw, s) == s.analysis_text


def test_strict_utf16_literal_equation_uses_original_math_namespace():
    ns = "http://purl.oclc.org/ooxml/officeDocument/math"
    raw, _ = source(
        f'<w:p><m:oMath xmlns:m="{ns}"><m:r><m:t>x=2</m:t></m:r></m:oMath></w:p>',
        strict=True,
        encoding="utf-16",
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "x=2"
    assert mapped_text(raw, s) == "x=2"


def test_team_synthetic_blocker_sample_reads_all_six_fragments():
    from hashlib import sha256
    from pathlib import Path

    raw = (Path(__file__).resolve().parents[1] / "fixtures/docx/word-blockers.docx").read_bytes()
    before = sha256(raw).hexdigest()
    s = build(raw)
    assert s.complete and len(s.fragments) == 6
    assert [f.text for f in s.fragments][-3:] == ["Перенос и ещё перенос.", "✓ Выполнено.", "x=2"]
    assert mapped_text(raw, s) == "".join(f.text for f in s.fragments)
    assert sha256(raw).hexdigest() == before


@pytest.mark.parametrize(
    "atom,kind",
    [
        ("<w:noBreakHyphen/>", "nonbreaking_hyphen"),
        ('<w:sym w:font="Wingdings" w:char="F0FC"/>', "symbol"),
    ],
)
def test_new_atom_survives_verified_result_codec_and_v5_wire_contract(atom, kind):
    import json
    from pathlib import Path

    from test_docx_word_integration import bundle

    from ara.docx_analysis import storage_codec as codec
    from ara.docx_analysis.presentation import present

    raw, _ = source("<w:p><w:r><w:t>Before</w:t>" + atom + "<w:t>After</w:t></w:r></w:p>")
    src, attempt, result = bundle(raw)
    assert src.source_data == raw
    assert codec.restore_result(src, attempt, result).wire_json == result.result_data
    result_body = json.loads(result.result_data)
    view = json.loads(present(src, attempt, result).wire_json)
    assert kind in {s["kind"] for s in result_body["findings"][0]["primary"]["slices"]}
    assert (
        view["findings"][0]["primary"]["slices"] == result_body["findings"][0]["primary"]["slices"]
    )
    for name in ("docx-review-v5.json", "docx-review-view-v5.json"):
        schema = json.loads((Path(__file__).resolve().parents[2] / "contracts" / name).read_text())
        assert set(schema["$defs"]["slice"]["properties"]["kind"]["enum"]) == {
            "text",
            "tab",
            "break",
            "nonbreaking_hyphen",
            "symbol",
        }
