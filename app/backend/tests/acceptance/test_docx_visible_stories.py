"""Current section stories are read once from their own original XML addresses."""

import io
import zipfile
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from docx_package_fixtures import build_package, relationships_xml
from test_docx_current_tables import history
from test_docx_grid_tables import gridless
from test_docx_move_catalog import group, resolve, run
from test_docx_retained_tables import marker
from test_docx_section_catalog import BASE, boundary, previous, reference, section
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_visible_main import DOC, SR, R, S, W, canonical, codes, payload, source
from test_docx_visible_styled_tables import table_style

PROFILE = "docx-analysis/final-visible-section-stories-v1"


def api():
    return import_module("ara.docx_analysis.visible_stories")


def story_xml(content, kind="header", *, strict=False, encoding="utf-8"):
    ns, rel = (S, SR) if strict else (W, R)
    tag = "hdr" if kind == "header" else "ftr"
    return (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<w:{tag} xmlns:w="{ns}" xmlns:r="{rel[:-1]}">{content}</w:{tag}>'
    ).encode(encoding)


def fixture(
    body=None,
    header=None,
    footer=None,
    *,
    strict=False,
    encoding="utf-8",
    styles=None,
    settings=None,
    main_links=(),
    header_links=(),
    extras=None,
    types=None,
):
    rel = SR if strict else R
    parts = {
        "custom/H.xml": story_xml(
            paragraph("Header") if header is None else header, strict=strict, encoding=encoding
        ),
        "custom/F.xml": story_xml(
            paragraph("Footer") if footer is None else footer,
            "footer",
            strict=strict,
            encoding=encoding,
        ),
    }
    content_types = {"custom/H.xml": BASE + "header+xml", "custom/F.xml": BASE + "footer+xml"}
    links = [
        {"Id": "H", "Type": rel + "header", "Target": "H.xml"},
        {"Id": "F", "Type": rel + "footer", "Target": "F.xml"},
        *main_links,
    ]
    if settings is not None:
        ns = S if strict else W
        parts["custom/Settings.xml"] = (
            f'<?xml version="1.0" encoding="{encoding}"?>'
            f'<w:settings xmlns:w="{ns}">{settings}</w:settings>'
        ).encode(encoding)
        content_types["custom/Settings.xml"] = BASE + "settings+xml"
        links.append({"Id": "settings", "Type": rel + "settings", "Target": "Settings.xml"})
    if header_links:
        parts["custom/_rels/H.xml.rels"] = relationships_xml(header_links, encoding=encoding)
    parts.update(extras or {})
    content_types.update(types or {})
    body = (
        paragraph("Body") + section(reference() + reference("F", "footer"))
        if body is None
        else body
    )
    raw, xml = source(
        body,
        styles,
        strict=strict,
        encoding=encoding,
        extra_parts=parts,
        extra_types=content_types,
        links=links,
    )
    return raw, xml, parts


def build(raw, **kw):
    return api().build_story_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest(), **kw
    )


def request(fragment, start=0, end=None):
    end = len(fragment.text) if end is None else end
    return api().VisibleSpanRequest(fragment.fragment_id, start, end, fragment.text[start:end])


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_main_then_canonical_story_order_exact_original_paths_and_manifest(strict, encoding):
    raw, xml, parts = fixture(strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and s.profile == PROFILE and s.main_part == "custom/Main.xml"
    assert s.analysis_text == "Body\n\nFooter\n\nHeader"
    assert [f.story_anchor.part_name for f in s.fragments] == [
        "custom/Main.xml",
        "custom/F.xml",
        "custom/H.xml",
    ]
    assert [f.story_anchor.path for f in s.fragments] == [(0,), (), ()]
    assert [f.paragraph_anchor.path for f in s.fragments] == [(0, 0), (0,), (0,)]
    assert [f.analysis_start for f in s.fragments] == [0, 6, 14]
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    assert sha256(raw).hexdigest() == s.source_sha256 and build(raw) == s
    for f in s.fragments:
        root = ET.fromstring(
            xml if f.story_anchor.part_name == s.main_part else parts[f.story_anchor.part_name]
        )
        assert resolve(root, f.pieces[0].anchor).text == f.text
        assert f.flow_anchor == f.story_anchor
    assert not any(e.status == "blocked" for e in s.coverage)


def test_inheritance_shared_parts_inactive_variants_and_orphan_content():
    old = previous(payload=reference("absent"))
    body = boundary(section(reference() + reference(variant="first"), history=old))
    body += paragraph("Body") + section(props="<w:titlePg/>")
    extra = {"custom/Orphan.xml": b'<bad xmlns="urn:synthetic"><text>DO NOT READ</text></bad>'}
    raw, _, _ = fixture(body, extras=extra, types={"custom/Orphan.xml": BASE + "header+xml"})
    s = build(raw)
    assert s.complete and s.analysis_text == "End\n\nBody\n\nHeader"
    assert sum(f.story_anchor.part_name == "custom/H.xml" for f in s.fragments) == 1
    assert ("excluded", "unreferenced_section_story") in codes(s)
    assert ("excluded", "historical_section_properties") in codes(s)
    assert "DO NOT READ" not in repr(s) + s.analysis_text


def test_first_and_even_definitions_selected_by_flags_without_per_page_repetition():
    refs = (
        reference()
        + reference("F", "footer")
        + reference("Fst", variant="first")
        + reference("Evn", variant="even")
    )
    extras = {
        "custom/First.xml": story_xml(paragraph("First")),
        "custom/Even.xml": story_xml(paragraph("Even")),
    }
    types = {p: BASE + "header+xml" for p in extras}
    links = [
        {"Id": "Fst", "Type": R + "header", "Target": "First.xml"},
        {"Id": "Evn", "Type": R + "header", "Target": "Even.xml"},
    ]
    raw, _, _ = fixture(
        paragraph("Body") + section(refs, "<w:titlePg/>"),
        settings="<w:evenAndOddHeaders/>",
        main_links=links,
        extras=extras,
        types=types,
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "Body\n\nEven\n\nFooter\n\nFirst\n\nHeader"
    assert ("metadata", "section_settings_accounted") in codes(s)


def test_header_tables_keep_neutral_styles_retained_revisions_grid_and_cell_flows():
    removed = cell(paragraph("OLD"), marker("cellDel"))
    kept = cell(paragraph("New 🧪"), marker("cellIns") + history("cell"))
    header = table(row(removed + kept, marker("ins")), 0, '<w:tblStyle w:val="T"/>')
    raw, _, parts = fixture(header=header, styles=table_style("T"))
    s = build(raw)
    assert s.complete and s.analysis_text == "Body\n\nFooter\n\nNew 🧪"
    f = s.fragments[-1]
    assert f.story_anchor.part_name == "custom/H.xml" and f.story_anchor.path == ()
    assert f.flow_anchor.path == (0, 2, 2)
    assert resolve(ET.fromstring(parts["custom/H.xml"]), f.pieces[0].anchor).text == "New 🧪"
    assert {
        ("metadata", "derived_table_grid"),
        ("metadata", "table_style_proven"),
        ("excluded", "deleted_table_cell"),
        ("excluded", "historical_table_properties"),
    } <= codes(s)


def test_nested_header_tables_have_distinct_original_flows():
    nested = table(row(cell(paragraph("Nested"))), 1)
    header = gridless(row(cell(paragraph("Outer") + nested + paragraph("Tail"))))
    s = build(fixture(header=header)[0])
    assert s.complete and s.analysis_text == "Body\n\nFooter\n\nOuter\n\nNested\n\nTail"
    assert [f.flow_anchor.path for f in s.fragments[-3:]] == [
        (0, 0, 0),
        (0, 0, 0, 1, 1, 0),
        (0, 0, 0),
    ]


def test_same_move_name_in_main_and_header_is_independent_and_source_side_is_excluded():
    moved = "<w:p>" + group(content=run("Old")) + group("To", content=run("Kept")) + "</w:p>"
    raw, _, _ = fixture(moved + section(reference()), header=moved)
    s = build(raw)
    assert s.complete and s.analysis_text == "Kept\n\nKept"
    assert s.fragments[0].fragment_id != s.fragments[1].fragment_id
    assert sum(e.code == "moved_source" for e in s.coverage) == 2


def test_moves_cannot_pair_across_different_stories():
    main = "<w:p>" + group() + "</w:p>" + section(reference())
    s = build(fixture(main, header="<w:p>" + group("To") + "</w:p>")[0])
    assert not s.complete and s.fragments == s.paragraphs == s.runs == () and s.analysis_text == ""


def test_header_hyperlink_uses_its_own_relationship_owner():
    header = '<w:p><w:hyperlink r:id="link">' + run("Header link") + "</w:hyperlink></w:p>"
    link = {
        "Id": "link",
        "Type": R + "hyperlink",
        "Target": "https://invalid.example",
        "TargetMode": "External",
    }
    good = build(fixture(header=header, header_links=[link])[0])
    assert good.complete and good.fragments[-1].text == "Header link"
    bad = build(fixture(header=header, main_links=[link])[0])
    assert not bad.complete and bad.fragments == ()


def test_hidden_header_runs_are_excluded_by_shared_original_styles():
    header = (
        "<w:p><w:r><w:t>A</w:t></w:r>"
        "<w:r><w:rPr><w:vanish/></w:rPr><w:t>HIDDEN</w:t></w:r>"
        "<w:r><w:t>B</w:t></w:r></w:p>"
    )
    s = build(fixture(header=header)[0])
    assert s.complete and s.fragments[-1].text == "AB" and ("excluded", "hidden_run") in codes(s)


@pytest.mark.parametrize(
    "header",
    [
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r></w:p>',
        "<w:sdt><w:sdtContent>" + paragraph("Hidden wrapper") + "</w:sdtContent></w:sdt>",
        section(reference()),
        "<w:p><w:r><w:t>Good</w:t><w:unknown/></w:r></w:p>",
    ],
)
def test_unsupported_current_story_content_is_global_atomic_failure(header):
    s = build(fixture(header=header)[0])
    assert not s.complete and s.fragments == s.paragraphs == s.runs == () and s.analysis_text == ""
    assert any(e.status == "blocked" for e in s.coverage)
    assert not any(e.status == "included" for e in s.coverage)
    assert ("excluded", "unreferenced_section_story") not in codes(s)


def test_unresolved_main_cannot_authorize_orphan_exclusion():
    body = "<w:unknown>" + paragraph("Unknown") + "</w:unknown>" + section(reference())
    s = build(fixture(body)[0])
    assert not s.complete and s.fragments == () and s.analysis_text == ""
    assert ("blocked", "story_usage_unproven") in codes(s)


def test_story_root_and_nested_section_metadata_are_not_invisible_text_bins():
    raw, _, _ = fixture()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["custom/H.xml"] = parts["custom/H.xml"].replace(b"w:hdr", b"w:ftr")
    assert not build(build_package(parts)).complete
    body = paragraph("Body") + section(reference(), "<w:pgMar>" + run("BAD") + "</w:pgMar>")
    s = build(fixture(body)[0])
    assert not s.complete and s.fragments == () and s.analysis_text == ""


def test_unknown_nonstory_parts_still_block_and_old_profile_still_refuses_stories():
    raw = fixture(
        extras={"custom/Unknown.xml": b"<unknown/>"},
        types={"custom/Unknown.xml": "application/xml"},
    )[0]
    s = build(raw)
    assert not s.complete and s.fragments == () and ("blocked", "unread_part") in codes(s)
    old = import_module("ara.docx_analysis.visible_grid_tables")
    raw = fixture()[0]
    s = old.build_grid_table_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert not s.complete and s.profile != PROFILE
