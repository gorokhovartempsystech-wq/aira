"""Final inline move view, literal independent text and original XML paths."""

from dataclasses import asdict, replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import PRIVATE, group, resolve, run
from test_docx_visible_main import DOC, canonical, codes, payload, rehash, source, style

PROFILE = "docx-analysis/final-visible-main-moves-v1"


def api():
    return import_module("ara.docx_analysis.visible_moves")


def build(raw, **kwargs):
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    return api().build_move_snapshot(raw, **(identity | kwargs))


def paired(destination=None, origin=None):
    return group(content=origin) + group("To", revision="12", content=destination)


def request(fragment, start=0, end=None):
    end = len(fragment.text) if end is None else end
    return api().VisibleSpanRequest(fragment.fragment_id, start, end, fragment.text[start:end])


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_final_text_manifest_and_original_destination_slices(strict, encoding):
    body = "<w:p>" + run("A") + group(content=run("OLD")) + run("B")
    body += group("To", revision="12", content=run("New🧪")) + run("C") + "</w:p>"
    raw, xml = source(body, strict=strict, encoding=encoding)
    before = raw
    s = build(raw)
    assert s.complete and s.analysis_text == "ABNew🧪C" and s.profile == PROFILE
    assert s.policy_version == "docx-analysis-policy/final-visible-no-comments-v2"
    assert s == build(raw) and s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    f = s.fragments[0]
    assert (
        f.fragment_id
        == "vf-"
        + sha256(
            canonical(
                dict(
                    domain="docx-visible-fragment/1",
                    profile=PROFILE,
                    policy_version=s.policy_version,
                    source_sha256=s.source_sha256,
                    story_anchor=asdict(f.story_anchor),
                    flow_anchor=asdict(f.flow_anchor),
                    paragraph_anchor=asdict(f.paragraph_anchor),
                )
            )
        ).hexdigest()
    )
    mapped = api().map_move_span(raw, s, fragment_id=f.fragment_id, start=1, end=7, quote="BNew🧪C")
    assert [(x.anchor.path, x.start, x.end) for x in mapped.slices] == [
        ((0, 0, 4, 0), 0, 1),
        ((0, 0, 6, 0, 0), 0, 4),
        ((0, 0, 8, 0), 0, 1),
    ]
    root = ET.fromstring(xml)
    assert [resolve(root, x.anchor).text[x.start : x.end] for x in mapped.slices] == [
        "B",
        "New🧪",
        "C",
    ]
    assert all(
        x.anchor.source_sha256 == s.source_sha256 and x.anchor.part_name == "custom/Main.xml"
        for x in mapped.slices
    )
    assert {
        ("excluded", "moved_source"),
        ("metadata", "moved_destination"),
        ("metadata", "move_range"),
    } <= codes(s)
    assert len([c for c in s.coverage if c.code == "move_range"]) == 4
    assert raw == before and PRIVATE not in repr(s) + repr(f)
    assert "OLD" not in s.analysis_text


def test_destination_before_source_in_different_paragraph_and_distinct_text():
    raw, _ = source(
        "<w:p>"
        + group("To", revision="3", content=run("NEW"))
        + "</w:p>"
        + "<w:p>"
        + run("Keep")
        + group(content=run("OLD"))
        + "</w:p>"
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "NEW\n\nKeep"
    assert [f.analysis_start for f in s.fragments] == [0, 5]
    results = api().map_move_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    assert [x.slices[0].anchor.path for x in results] == [(0, 0, 1, 0, 0), (0, 1, 0, 0)]


def test_range_is_not_moved_content_and_multiple_members_keep_document_order():
    first = '<w:moveFromRangeStart w:id="0" w:name="X"/>' + run("Keep")
    first += '<w:moveFrom w:id="99">' + run("OLD") + '</w:moveFrom><w:moveFromRangeEnd w:id="0"/>'
    second = '<w:moveToRangeStart w:id="0" w:name="X"/>'
    second += '<w:moveTo w:id="3">' + run("A") + "</w:moveTo>" + run("B")
    second += '<w:moveTo w:id="4">' + run("C") + '</w:moveTo><w:moveToRangeEnd w:id="0"/>'
    raw, _ = source("<w:p>" + first + second + "</w:p>")
    s = build(raw)
    assert s.complete and s.analysis_text == "KeepABC"
    result = api().map_move_spans(raw, s, requests=(request(s.fragments[0]),))[0]
    assert [x.anchor.path for x in result.slices] == [
        (0, 0, 1, 0),
        (0, 0, 5, 0, 0),
        (0, 0, 6, 0),
        (0, 0, 7, 0, 0),
    ]


def test_destination_visibility_revisions_comments_and_unicode_atoms():
    destination = run("a") + '<w:r><w:rPr><w:rStyle w:val="Hidden"/></w:rPr><w:t>SECRET</w:t></w:r>'
    destination += '<w:del w:id="8"><w:r><w:delText>DELETED</w:delText></w:r></w:del>'
    destination += (
        '<w:ins w:id="9"><w:hyperlink w:anchor="Here">' + run("😀é") + "</w:hyperlink></w:ins>"
    )
    destination += '<w:commentRangeStart w:id="1"/><w:commentRangeEnd w:id="1"/>'
    destination += '<w:r><w:commentReference w:id="1"/><w:tab/><w:br/><w:t>Я</w:t></w:r>'
    raw, xml = source(
        "<w:p>" + paired(destination) + "</w:p>",
        style("Hidden", "<w:rPr><w:vanish/></w:rPr>", "character"),
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "a😀é\t\nЯ"
    assert len(s.runs) == 4 and s.runs[1].visibility.hidden
    assert {
        ("excluded", "hidden_run"),
        ("excluded", "deleted_content"),
        ("excluded", "comments_policy"),
    } <= codes(s)
    result = api().map_move_spans(raw, s, requests=(request(s.fragments[0]),))[0]
    assert [x.kind for x in result.slices] == ["text", "text", "tab", "break", "text"]
    root = ET.fromstring(xml)
    assert [resolve(root, x.anchor).tag.rsplit("}", 1)[-1] for x in result.slices] == [
        "t",
        "t",
        "tab",
        "br",
        "t",
    ]
    assert result.slices[1].anchor.path == (0, 0, 4, 3, 0, 0, 0)
    assert PRIVATE not in repr(s) and "SECRET" not in repr(s.runs)


@pytest.mark.parametrize("prop", ["specVanish", "webHidden"])
def test_ordinary_destination_run_property_does_not_hide(prop):
    raw, _ = source(
        "<w:p>" + paired(f"<w:r><w:rPr><w:{prop}/></w:rPr><w:t>A</w:t></w:r>") + "</w:p>"
    )
    assert build(raw).analysis_text == "A"


def test_source_excluded_payload_empty_destination_and_direct_hidden_override():
    dest = '<w:r><w:rPr><w:rStyle w:val="Hidden"/><w:vanish w:val="0"/></w:rPr><w:t>A</w:t></w:r>'
    raw, _ = source(
        "<w:p>" + paired(dest, "<s:unknown>ignored source</s:unknown>") + "</w:p>",
        style("Hidden", "<w:rPr><w:vanish/></w:rPr>", "character"),
    )
    assert build(raw).complete and build(raw).analysis_text == "A"
    raw, _ = source(
        "<w:p>" + paired("<w:r><w:rPr><w:vanish/></w:rPr><w:t>SECRET</w:t></w:r>") + "</w:p>"
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "" and s.fragments == ()
    assert api().map_move_spans(raw, s, requests=()) == ()


@pytest.mark.parametrize(
    "body,code",
    [
        ("<w:p>" + group() + "</w:p>", "move_catalog_blocked"),
        (
            '<w:p><w:pPr><w:rPr><w:moveFrom w:id="1"/></w:rPr></w:pPr>' + run() + "</w:p>",
            "move_catalog_blocked",
        ),
        ('<w:p><w:del w:id="1">' + paired() + "</w:del></w:p>", "move_catalog_blocked"),
        ("<w:p>" + paired("<s:unknown/>") + "</w:p>", "unsupported_main_flow"),
        ("<w:p>" + paired() + "</w:p><w:tbl/>", "unsupported_main_flow"),
        (
            '<w:p><w:pPr><w:rPr><w:del w:id="7"/></w:rPr></w:pPr>' + paired() + "</w:p>",
            "unsupported_main_flow",
        ),
        (
            "<w:p><w:pPr><w:rPr><w:vanish/></w:rPr></w:pPr>" + paired() + "</w:p>",
            "unresolved_paragraph_boundary",
        ),
    ],
)
def test_unsupported_moves_flows_and_paragraph_boundaries_never_partial(body, code):
    raw, _ = source(body)
    s = build(raw)
    assert (
        not s.complete
        and s.analysis_text == ""
        and s.fragments == ()
        and s.runs == ()
        and s.paragraphs == ()
    )
    assert ("blocked", code) in codes(s)
    assert api().map_move_spans(raw, s, requests=()) == ()


def test_other_parts_do_not_inherit_main_catalog_readiness():
    raw, _ = source(
        "<w:p>" + paired() + "</w:p>",
        extra_parts={"other.bin": b"synthetic"},
        extra_types={"other.bin": "application/octet-stream"},
    )
    s = build(raw)
    assert not s.complete and ("blocked", "unread_part") in codes(s)
    assert s.analysis_text == "Moved 🧪"


def test_profiles_mutually_rejected_and_existing_admission_unchanged():
    old = import_module("ara.docx_analysis.visible_main")
    raw, _ = source("<w:p>" + paired() + "</w:p>")
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    assert not old.build_visible_snapshot(raw, **identity).complete
    raw, _ = source("<w:p>" + run("A") + "</w:p>")
    identity["source_sha256"] = sha256(raw).hexdigest()
    previous, current = old.build_visible_snapshot(raw, **identity), build(raw)
    assert previous.analysis_text == current.analysis_text == "A"
    assert previous.fragments[0].fragment_id != current.fragments[0].fragment_id
    error("invalid_snapshot", lambda: old.map_visible_spans(raw, current, requests=()))
    error("invalid_snapshot", lambda: api().map_move_spans(raw, previous, requests=()))
    error(
        "invalid_snapshot",
        lambda: api().map_move_spans(raw, rehash(replace(previous, profile=PROFILE)), requests=()),
    )


def test_forged_text_provenance_digest_and_source_are_not_authentication():
    raw, _ = source("<w:p>" + run("A") + paired(run("BC")) + "</w:p>")
    s = build(raw)
    f = s.fragments[0]
    for fake in (
        replace(s, analysis_text="fake"),
        replace(s, complete=False),
        replace(s, fragments=(replace(f, text="fake"),)),
        replace(
            s,
            fragments=(
                replace(
                    f, pieces=(replace(f.pieces[0], anchor=f.pieces[-1].anchor),) + f.pieces[1:]
                ),
            ),
        ),
        replace(s, coverage=()),
    ):
        error(
            "invalid_snapshot",
            lambda fake=fake: api().map_move_spans(raw, rehash(fake), requests=()),
        )
    error("source_mismatch", lambda: build(raw, source_sha256="0" * 64))
    other, _ = source("<w:p>" + run("A") + paired(run("BD")) + "</w:p>")
    error("source_mismatch", lambda: api().map_move_spans(other, s, requests=()))


def test_batch_rebuilds_move_and_style_catalogs_once(monkeypatch):
    moves = import_module("ara.docx_analysis.moves")
    shared = import_module("ara.docx_analysis.visible_main._build")
    raw, _ = source("<w:p>" + paired(run("ABC")) + "</w:p>")
    s = build(raw)
    calls = []
    original_moves, original_styles = moves.read_move_catalog, shared.read_style_context

    def moved(*args, **kwargs):
        calls.append("moves")
        return original_moves(*args, **kwargs)

    def styled(*args, **kwargs):
        calls.append("styles")
        return original_styles(*args, **kwargs)

    monkeypatch.setattr(moves, "read_move_catalog", moved)
    monkeypatch.setattr(shared, "read_style_context", styled)
    result = api().map_move_spans(raw, s, requests=(request(s.fragments[0]),) * 100)
    assert len(result) == 100 and all(x == result[0] for x in result)
    assert sorted(calls) == ["moves", "styles"]
