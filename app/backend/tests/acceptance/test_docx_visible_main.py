"""Source-backed visible main acceptance, frozen before implementation."""

import json
from dataclasses import asdict, fields, replace
from hashlib import sha256
from importlib import import_module
from uuid import UUID
from xml.etree import ElementTree as ET

import pytest
from docx_projection_fixtures import package

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://purl.oclc.org/ooxml/wordprocessingml/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
SR = "http://purl.oclc.org/ooxml/officeDocument/relationships/"
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
DOC = UUID("12345678-1234-4234-8234-123456789abc")
GAP = (
    "<w:p><w:r><w:t>ab</w:t></w:r>"
    "<w:r><w:rPr><w:vanish/></w:rPr><w:t>SECRET</w:t></w:r>"
    "<w:r><w:t>cd</w:t></w:r></w:p>"
)


def api():
    return import_module("ara.docx_analysis.visible_main")


def source(body=GAP, styles=None, *, strict=False, encoding="utf-8", **kwargs):
    extras = dict(kwargs.pop("extra_parts", {}))
    types = dict(kwargs.pop("extra_types", {}))
    links = list(kwargs.pop("links", ()))
    if styles is not None:
        extras["custom/Styles.xml"] = (
            f'<?xml version="1.0" encoding="{encoding}"?>'
            f'<w:styles xmlns:w="{S if strict else W}">{styles}</w:styles>'
        ).encode(encoding)
        types["custom/Styles.xml"] = MIME
        links.append(
            {"Id": "styles", "Type": (SR if strict else R) + "styles", "Target": "Styles.xml"}
        )
    return package(
        body,
        main_part="custom/Main.xml",
        strict=strict,
        encoding=encoding,
        extra_parts=extras,
        extra_types=types,
        links=links,
        **kwargs,
    )


def style(key, props="", kind="paragraph", attrs=""):
    return f'<w:style w:styleId="{key}" w:type="{kind}" {attrs}>{props}</w:style>'


def build(raw, **kwargs):
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    return api().build_visible_snapshot(raw, **(identity | kwargs))


def request(f, start=0, end=None):
    end = len(f.text) if end is None else end
    return api().VisibleSpanRequest(f.fragment_id, start, end, f.text[start:end])


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def payload(s):
    value = asdict(s)
    value.pop("snapshot_sha256")
    value["document_id"] = str(s.document_id)
    value["storage_revision"] = str(s.storage_revision)
    return value


def rehash(s):
    s = replace(s, text_sha256=sha256(s.analysis_text.encode()).hexdigest())
    return replace(s, snapshot_sha256=sha256(canonical(payload(s))).hexdigest())


def codes(s):
    return {(c.status, c.code) for c in s.coverage}


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_literal_gap_source_paths_unicode_and_manifest(strict, encoding):
    raw, _ = source(strict=strict, encoding=encoding, comment=b"legal PK\x05\x06 archive comment")
    s = build(raw)
    assert s.complete and s.analysis_text == "abcd"
    assert s.profile == "docx-analysis/final-visible-main-v1"
    assert s.policy_version == "docx-analysis-policy/final-visible-no-comments-v2"
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    f = s.fragments[0]
    assert (
        f.fragment_id
        == "vf-"
        + sha256(
            canonical(
                dict(
                    domain="docx-visible-fragment/1",
                    profile=s.profile,
                    policy_version=s.policy_version,
                    source_sha256=s.source_sha256,
                    story_anchor=asdict(f.story_anchor),
                    flow_anchor=asdict(f.flow_anchor),
                    paragraph_anchor=asdict(f.paragraph_anchor),
                )
            )
        ).hexdigest()
    )
    result = api().map_visible_span(raw, s, fragment_id=f.fragment_id, start=1, end=3, quote="bc")
    assert [(x.anchor.path, x.start, x.end) for x in result.slices] == [
        ((0, 0, 0, 0), 1, 2),
        ((0, 0, 2, 0), 0, 1),
    ]
    assert [r.visibility.status for r in s.runs] == ["visible", "hidden", "visible"]
    assert s.runs[1].direct_properties.vanish.anchor.path == (0, 0, 1, 0, 0)
    assert ("excluded", "hidden_run") in codes(s)
    assert "SECRET" not in repr(s) + repr(f) + repr(request(f))
    assert sha256(raw).hexdigest() == s.source_sha256


def test_unicode_atoms_empty_paragraphs_and_separators():
    raw, _ = source(
        "<w:p/><w:p><w:r><w:t>  </w:t></w:r></w:p>"
        + GAP
        + "<w:p><w:r><w:t>😀é</w:t><w:tab/><w:br/><w:cr/><w:t>Я</w:t></w:r></w:p>"
    )
    s = build(raw)
    assert s.analysis_text == "abcd\n\n😀é\t\n\nЯ"
    assert [f.analysis_start for f in s.fragments] == [0, 6]
    assert len(s.paragraphs) == 4
    f = s.fragments[1]
    mapped = api().map_visible_spans(raw, s, requests=(request(f), request(f)))
    assert mapped[0] == mapped[1]
    assert [x.kind for x in mapped[0].slices] == ["text", "tab", "break", "break", "text"]


def test_xml_selectors_based_on_and_real_definition_provenance():
    styles = style("P", attrs='w:default="1"') + style(
        "Base", "<w:rPr><w:vanish/></w:rPr>", "character"
    )
    styles += style("C", '<w:basedOn w:val="Base"/>', "character")
    body = (
        '<w:p><w:pPr><w:pStyle w:val="P"/></w:pPr>'
        '<w:r><w:rPr><w:rStyle w:val="C"/></w:rPr><w:t>x</w:t></w:r></w:p>'
    )
    raw, _ = source(body, styles)
    s = build(raw)
    assert s.complete and s.fragments == () and s.analysis_text == ""
    assert s.paragraphs[0].style_reference_anchor.path == (0, 0, 0, 0)
    assert s.paragraphs[0].resolved_style_id == "P"
    assert s.runs[0].style_reference_anchor.path == (0, 0, 1, 0, 0)
    assert s.runs[0].resolved_style_id == "C" and s.runs[0].visibility.hidden
    inherited = next(x for x in s.style_context.styles if x.style_id == "C")
    assert inherited.properties.vanish.anchor.path == (1, 0, 0)
    assert inherited.properties.vanish.anchor.part_name == "custom/Styles.xml"
    assert ("metadata", "style_context_accounted") in codes(s)
    raw2, _ = source(
        body.replace('<w:rStyle w:val="C"/>', '<w:rStyle w:val="C"/><w:vanish w:val="0"/>'), styles
    )
    s2 = build(raw2)
    assert s2.analysis_text == "x" and s2.runs[0].direct_properties.vanish.value is False


@pytest.mark.parametrize("prop", ["specVanish", "webHidden"])
def test_ordinary_metadata_does_not_hide_text(prop):
    raw, _ = source(f"<w:p><w:r><w:rPr><w:{prop}/></w:rPr><w:t>x</w:t></w:r></w:p>")
    assert build(raw).analysis_text == "x"


@pytest.mark.parametrize("value", ["0", "1"])
@pytest.mark.parametrize("prop", ["vanish", "specVanish", "webHidden"])
def test_implicit_default_guard_including_explicit_false(prop, value):
    raw, _ = source(
        styles=style(
            "C", f'<w:rPr><w:{prop} w:val="{value}"/></w:rPr>', "character", 'w:default="1"'
        )
    )
    s = build(raw)
    assert not s.complete and s.fragments == () and s.runs == () and s.paragraphs == ()
    assert ("blocked", "implicit_character_style") in codes(s)


@pytest.mark.parametrize("where", ["mark", "paragraph", "default"])
@pytest.mark.parametrize("prop", ["vanish", "specVanish"])
def test_boundary_guard_does_not_guess_joins(where, prop):
    styles = None
    body = "<w:p><w:r><w:t>x</w:t></w:r></w:p>"
    if where == "mark":
        body = body.replace("<w:p>", f"<w:p><w:pPr><w:rPr><w:{prop}/></w:rPr></w:pPr>")
    elif where == "paragraph":
        styles = style("P", f"<w:rPr><w:{prop}/></w:rPr>", attrs='w:default="1"')
    else:
        styles = (
            f"<w:docDefaults><w:rPrDefault><w:rPr><w:{prop}/>"
            "</w:rPr></w:rPrDefault></w:docDefaults>"
        )
    s = build(source(body, styles)[0])
    assert ("blocked", "unresolved_paragraph_boundary") in codes(s)
    assert s.analysis_text == "" and s.runs == ()


@pytest.mark.parametrize("payload", ["<w:fldChar/>", "<w:drawing/>", "<s:unknown/>"])
def test_hidden_unknown_payload_still_blocks_but_deleted_history_are_excluded(payload):
    raw, _ = source(f"<w:p><w:r><w:rPr><w:vanish/></w:rPr>{payload}</w:r></w:p>")
    assert ("blocked", "unsupported_main_flow") in codes(build(raw))
    body = '<w:p><w:pPr><w:pPrChange w:id="1"><w:pPr>' + payload + "</w:pPr></w:pPrChange></w:pPr>"
    body += (
        '<w:del w:id="2">'
        + payload
        + '</w:del><w:ins w:id="3"><w:r><w:t>kept</w:t></w:r></w:ins></w:p>'
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "kept"
    assert {("excluded", "deleted_content"), ("excluded", "historical_properties")} <= codes(s)


@pytest.mark.parametrize(
    "body",
    [
        '<w:p><w:pPr><w:rPr><w:del w:id="1"/></w:rPr></w:pPr></w:p>',
        '<w:p><w:pPr><w:rPr><w:rStyle w:val="C"/></w:rPr></w:pPr></w:p>',
        '<w:p><w:pPr><w:numPr><w:numId w:val="0"/></w:numPr></w:pPr></w:p>',
        "<w:tbl/>",
        '<w:p><w:r><w:t s:unknown="1">x</w:t></w:r></w:p>',
        "<w:p><w:r><w:rPr><w:vanish/><w:vanish/></w:rPr></w:r></w:p>",
        "<w:p><w:r><w:t>x</w:t>bad</w:r></w:p>",
        '<w:p><w:hyperlink r:id="missing"><w:r><w:t>x</w:t></w:r></w:hyperlink></w:p>',
    ],
)
def test_unsupported_main_never_emits_partial_context_or_text(body):
    s = build(source(GAP + body)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == s.runs == s.paragraphs == ()
    assert [(c.status, c.code) for c in s.coverage if c.anchor is not None] == [
        ("blocked", "unsupported_main_flow")
    ]


def test_comments_properties_mark_insertion_and_ledger():
    body = '<w:p><w:pPr><w:rPr><w:ins w:id="9"/></w:rPr></w:pPr>'
    body += '<w:bookmarkStart w:id="1" w:name="Synthetic"/><w:commentRangeStart w:id="2"/>'
    body += '<w:r><w:rPr><w:rPrChange w:id="3"><w:rPr><w:vanish/></w:rPr></w:rPrChange></w:rPr>'
    body += (
        '<w:t>x</w:t><w:commentReference w:id="2"/></w:r>'
        '<w:commentRangeEnd w:id="2"/><w:bookmarkEnd w:id="1"/></w:p>'
    )
    comments = (
        f'<w:comments xmlns:w="{W}"><w:comment w:id="2">'
        "<w:p><w:r><w:t>SECRET</w:t></w:r></w:p></w:comment></w:comments>"
    ).encode()
    raw, _ = source(
        body,
        extra_parts={"custom/Comments.xml": comments},
        extra_types={"custom/Comments.xml": MIME.replace("styles", "comments")},
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "x"
    assert ("metadata", "inserted_boundary") in codes(s)
    assert ("excluded", "historical_properties") in codes(s)
    assert len([c for c in s.coverage if c.anchor is None]) == 4


def test_auxiliary_blocker_preserves_valid_main_and_style_change_binds_identity():
    raw, _ = source(styles=style("Unused"), extra_parts={"other.bin": b"x"})
    s = build(raw)
    assert not s.complete and s.analysis_text == "abcd"
    assert ("blocked", "unread_part") in codes(s)
    raw2, _ = source(styles=style("Different"), extra_parts={"other.bin": b"x"})
    s2 = build(raw2)
    assert s.text_sha256 == s2.text_sha256
    assert s.snapshot_sha256 != s2.snapshot_sha256
    assert s.fragments[0].fragment_id != s2.fragments[0].fragment_id


@pytest.mark.parametrize("target", ["piece", "coverage", "direct", "catalog", "paragraph"])
def test_rehashed_forged_snapshots_fail_against_original_source(target):
    raw, _ = source()
    s = build(raw)
    if target == "piece":
        f = s.fragments[0]
        forged = replace(f.pieces[0], anchor=replace(f.pieces[0].anchor, path=(0, 0, 1, 1)))
        s = replace(s, fragments=(replace(f, pieces=(forged, *f.pieces[1:])),))
    elif target == "coverage":
        s = replace(s, coverage=tuple(c for c in s.coverage if c.code != "hidden_run"))
    elif target == "direct":
        r = s.runs[1]
        value = replace(
            r.direct_properties.vanish,
            anchor=replace(r.direct_properties.vanish.anchor, path=(0, 0, 0, 0)),
        )
        s = replace(
            s,
            runs=(
                s.runs[0],
                replace(r, direct_properties=replace(r.direct_properties, vanish=value)),
                s.runs[2],
            ),
        )
    elif target == "catalog":
        s = replace(s, style_context=replace(s.style_context, context_sha256="0" * 64))
    else:
        s = replace(s, paragraphs=(replace(s.paragraphs[0], resolved_style_id="forged"),))
    s = rehash(s)
    error("invalid_snapshot", lambda: api().map_visible_spans(raw, s, requests=()))


def test_mapping_errors_empty_validation_and_atomicity():
    raw, _ = source()
    s = build(raw)
    f = s.fragments[0]
    valid = request(f)
    assert api().map_visible_spans(raw, s, requests=()) == ()
    for bad, code in [
        (replace(valid, quote="wrong"), "invalid_span"),
        (replace(valid, start=True), "invalid_input"),
        (replace(valid, start=-1), "invalid_span"),
        (replace(valid, end=999), "invalid_span"),
        (replace(valid, fragment_id="missing"), "unknown_fragment"),
    ]:
        error(code, lambda: api().map_visible_spans(raw, s, requests=(valid, bad)))
    raw2, _ = source("<w:p/>")
    error("source_mismatch", lambda: api().map_visible_spans(raw2, s, requests=()))
    error(
        "invalid_snapshot",
        lambda: api().map_visible_spans(raw, replace(s, complete=1), requests=()),
    )
    error("invalid_input", lambda: api().map_visible_spans(raw, s, requests=[valid]))


def test_limits_total_xml_preflight_hidden_history_and_mapping_output():
    raw, xml = source()
    root = ET.fromstring(xml)
    nodes = sum(1 for _ in root.iter())
    chars = sum(
        len(n.text or "") + len(n.tail or "") + sum(map(len, n.attrib.values()))
        for n in root.iter()
    )
    assert build(
        raw, limits=api().VisibleLimits(max_xml_nodes=nodes, max_xml_characters=chars)
    ).complete
    for kwargs in [
        dict(max_xml_nodes=nodes - 1),
        dict(max_xml_characters=chars - 1),
        dict(max_xml_depth=4),
        dict(max_runs=2),
        dict(max_pieces=2),
        dict(max_text_characters=3),
        dict(max_coverage_items=1),
    ]:
        error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(**kwargs)))
    s = build(raw)
    manifest_size = len(canonical(payload(s)))
    assert build(raw, limits=api().VisibleLimits(max_manifest_bytes=manifest_size)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_manifest_bytes=manifest_size - 1)),
    )
    f = s.fragments[0]
    for kwargs in [
        dict(max_span_requests=1),
        dict(max_requested_characters=7),
        dict(max_mapped_slices=3),
    ]:
        error(
            "view_limit_exceeded",
            lambda: api().map_visible_spans(
                raw, s, requests=(request(f), request(f)), limits=api().VisibleLimits(**kwargs)
            ),
        )
    raw_styles, _ = source(styles=style("P"))
    error(
        "view_limit_exceeded",
        lambda: build(raw_styles, limits=api().VisibleLimits(max_xml_nodes=nodes)),
    )
    for field in fields(api().VisibleLimits):
        if field.name != "styles":
            error("invalid_input", lambda: api().VisibleLimits(**{field.name: True}))
    limits = api().VisibleLimits()
    object.__setattr__(limits, "max_runs", 0)
    error("invalid_input", lambda: build(raw, limits=limits))


def test_batch_rebuilds_catalog_once(monkeypatch):
    raw, _ = source(styles=style("P"))
    s = build(raw)
    module = import_module("ara.docx_analysis.visibility._read")
    calls = []
    original = module.read_style_context

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    # Locate the builder's binding without requiring an internal module layout.
    builder_module = import_module(api().build_visible_snapshot.__module__)
    monkeypatch.setattr(builder_module, "read_style_context", spy)
    results = api().map_visible_spans(raw, s, requests=(request(s.fragments[0]),) * 1000)
    assert len(results) == 1000 and len(calls) == 1


@pytest.mark.parametrize(
    "definition,code",
    [
        ("", "missing_paragraph_style"),
        (style("P", kind="character"), "paragraph_style_type_mismatch"),
        (style("P", '<w:basedOn w:val="P"/>'), "unresolved_paragraph_style"),
    ],
)
def test_selected_style_refusal_and_unused_opaque(definition, code):
    body = '<w:p><w:pPr><w:pStyle w:val="P"/></w:pPr></w:p>'
    s = build(source(body, definition)[0])
    assert ("blocked", code) in codes(s)
    unused = style("Unused", "<w:unknown/>") + style("Table", kind="table")
    s2 = build(source(styles=unused)[0])
    assert s2.complete and s2.analysis_text == "abcd"


def test_exact_inputs_limits_and_corrupted_snapshot_shape():
    raw, _ = source()
    for kwargs in [
        dict(storage_revision=True),
        dict(document_id=str(DOC)),
        dict(source_sha256="A" * 64),
        dict(limits={}),
    ]:
        error("invalid_input", lambda: build(raw, **kwargs))
    s = build(raw)
    for replacement in [
        dict(fragments=list(s.fragments)),
        dict(runs=(object(),)),
        dict(profile="old"),
        dict(coverage=()),
        dict(snapshot_sha256="0" * 64),
    ]:
        error(
            "invalid_snapshot",
            lambda: api().map_visible_spans(raw, replace(s, **replacement), requests=()),
        )
