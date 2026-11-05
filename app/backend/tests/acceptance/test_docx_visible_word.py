"""Independent ordinary templates, exact metadata roles and original-source mappings."""

import io
import re
import zipfile
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_visible_main import DOC, payload, rehash
from test_docx_visible_main import canonical as canonical_dict
from test_docx_visible_style_lists import fixture, repack, styled

ROOT = Path(__file__).resolve().parents[1] / "fixtures/docx/common-template"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
PROFILE = "docx-analysis/final-visible-word-package-v1"
STYLE_PROFILE = "docx-visibility/mc-word-package-styles-v1"
CASES = ("plain", "headings", "bullet", "numbered", "table", "merged_table")


def canonical(snapshot):
    return canonical_dict(payload(snapshot) | {"snapshot_sha256": snapshot.snapshot_sha256})


def api():
    return import_module("ara.docx_analysis.visible_word")


def source(case="plain"):
    return (ROOT / (case + ".docx")).read_bytes()


def parts(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return {name: z.read(name) for name in z.namelist()}


def build(raw, **kw):
    return api().build_word_snapshot(
        raw,
        **(dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()) | kw),
    )


def alter(raw, name, transform):
    entries = parts(raw)
    raw_xml = entries[name]
    namespaces = dict(
        (prefix, uri)
        for event, (prefix, uri) in ET.iterparse(io.BytesIO(raw_xml), events=("start-ns",))
    )
    root = ET.fromstring(raw_xml)
    transform(root)
    for prefix, uri in namespaces.items():
        if prefix and not prefix.startswith("ns"):
            ET.register_namespace(prefix, uri)
    serialized = ET.tostring(root)
    for prefix, uri in namespaces.items():
        declaration = ("xmlns:" + prefix + "=").encode() if prefix else b"xmlns="
        if declaration not in serialized:
            root.set("xmlns:" + prefix if prefix else "xmlns", uri)
    entries[name] = ET.tostring(root)
    return repack(entries)


def blocked(raw):
    snapshot = build(raw)
    assert not snapshot.complete
    assert snapshot.analysis_text == ""
    assert snapshot.fragments == snapshot.lists == snapshot.references == ()
    assert any(item.status == "blocked" for item in snapshot.coverage)
    return snapshot


def error(code, call):
    with pytest.raises(api().VisibleViewError) as exc:
        call()
    assert exc.value.code == code


def original(raw, snapshot):
    entries = parts(raw)
    requests = tuple(
        api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text) for f in snapshot.fragments
    )
    mapped = api().map_word_spans(raw, snapshot, requests=requests)
    assert len(mapped) == len(snapshot.fragments)
    for f, span in zip(snapshot.fragments, mapped, strict=True):
        values = []
        for piece in span.slices:
            assert piece.anchor.source_sha256 == sha256(raw).hexdigest()
            node = resolve(ET.fromstring(entries[piece.anchor.part_name]), piece.anchor)
            value = node.text if piece.kind == "text" else "\t" if piece.kind == "tab" else "\n"
            values.append(value[piece.start : piece.end])
        assert "".join(values) == f.text
    for item in snapshot.lists:
        for anchor, tag in (
            (item.paragraph_anchor, "p"),
            (item.properties_anchor, "numPr"),
            (item.definition_anchor, "lvl"),
            (item.instance_anchor, "num"),
        ):
            assert resolve(ET.fromstring(entries[anchor.part_name]), anchor).tag == W + tag
        for anchor in item.style_chain:
            assert resolve(ET.fromstring(entries[anchor.part_name]), anchor).tag == W + "style"


@pytest.mark.parametrize("case", CASES)
def test_independent_default_template_reads_every_literal_and_preserves_original(case):
    raw = source(case)
    before = parts(raw)
    snapshot = build(raw)
    assert type(snapshot) is api().WordSnapshot
    assert snapshot.complete and snapshot.profile == PROFILE
    assert snapshot.style_context.profile == STYLE_PROFILE
    expected = [n.text for n in ET.fromstring(before["word/document.xml"]).iter(W + "t") if n.text]
    assert "".join(f.text for f in snapshot.fragments) == "".join(expected)
    assert bool(snapshot.lists) == (case in ("bullet", "numbered"))
    assert {i.numbering_source for i in snapshot.lists} <= {"style"}
    original(raw, snapshot)
    assert parts(raw) == before and source(case) == raw
    assert canonical(build(raw)) == canonical(snapshot)


@pytest.mark.parametrize("case", CASES)
def test_old_profile_remains_fixed_and_refuses_template(case):
    from ara.docx_analysis.visible_style_lists import build_style_list_snapshot

    raw = source(case)
    old = build_style_list_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert not old.complete and old.fragments == old.lists == ()


@pytest.mark.parametrize(
    "part",
    (
        "word/fontTable.xml",
        "word/webSettings.xml",
        "word/theme/theme1.xml",
        "word/stylesWithEffects.xml",
        "customXml/item1.xml",
        "customXml/itemProps1.xml",
    ),
)
def test_auxiliary_unknown_content_refuses_atomically(part):
    raw = alter(source(), part, lambda root: ET.SubElement(root, W + "t"))
    blocked(raw)


@pytest.mark.parametrize(
    "rid", ("fontTable", "webSettings", "theme", "stylesWithEffects", "customXml")
)
@pytest.mark.parametrize("fault", ("wrong_type", "external", "duplicate", "unlinked"))
def test_relationship_proof_is_not_a_mime_whitelist(rid, fault):
    def change(root):
        link = next(n for n in root if n.get("Type").endswith("/" + rid))
        if fault == "wrong_type":
            link.set("Type", "urn:unproved")
        elif fault == "external":
            link.set("TargetMode", "External")
            link.set("Target", "https://invalid.example/never-fetch")
        elif fault == "duplicate":
            duplicate = ET.fromstring(ET.tostring(link))
            duplicate.set("Id", "ExtraUnproved")
            root.append(duplicate)
        else:
            root.remove(link)

    blocked(alter(source(), "word/_rels/document.xml.rels", change))


def test_effects_style_visibility_conflict_refuses():
    def conflict(root):
        style = next(n for n in root if n.get(W + "styleId") == "Normal")
        ET.SubElement(ET.SubElement(style, W + "rPr"), W + "vanish")

    blocked(alter(source(), "word/stylesWithEffects.xml", conflict))


def test_base_only_style_becomes_relevant_and_refuses():
    def selector(root):
        paragraph = next(root.iter(W + "p"))
        props = ET.Element(W + "pPr")
        ET.SubElement(props, W + "pStyle", {W + "val": "Header"})
        paragraph.insert(0, props)

    blocked(alter(source(), "word/document.xml", selector))


def test_nonempty_bibliography_is_not_silently_discarded():
    blocked(
        alter(
            source(),
            "customXml/item1.xml",
            lambda root: ET.SubElement(
                root, "{http://schemas.openxmlformats.org/officeDocument/2006/bibliography}Source"
            ),
        )
    )


def test_thumbnail_cannot_double_as_content_image():
    def edge(root):
        ET.SubElement(
            root,
            REL + "Relationship",
            {
                "Id": "ThumbAsContent",
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                "Target": "../docProps/thumbnail.jpeg",
            },
        )

    blocked(alter(source(), "word/_rels/document.xml.rels", edge))


@pytest.mark.parametrize("fault", ("invalid", "child", "attribute", "duplicate"))
def test_contextual_spacing_has_closed_boolean_leaf_shape(fault):
    def broken(root):
        for style in root:
            if style.get(W + "styleId") != "ListNumber":
                continue
            prop = style.find(W + "pPr")
            leaf = prop.find(W + "contextualSpacing")
            if fault == "invalid":
                leaf.set(W + "val", "maybe")
            elif fault == "child":
                ET.SubElement(leaf, W + "vanish")
            elif fault == "attribute":
                leaf.set(W + "unproved", "1")
            else:
                prop.append(ET.fromstring(ET.tostring(leaf)))

    raw = source("numbered")
    for part in ("word/styles.xml", "word/stylesWithEffects.xml"):
        raw = alter(raw, part, broken)
    blocked(raw)


def test_empty_map_reproves_full_source_and_cannot_trust_rehashed_snapshot():
    raw = source()
    snapshot = build(raw)
    assert api().map_word_spans(raw, snapshot, requests=()) == ()
    forged = rehash(replace(snapshot, analysis_text=snapshot.analysis_text + "forged"))
    error("invalid_snapshot", lambda: api().map_word_spans(raw, forged, requests=()))
    error("source_mismatch", lambda: api().map_word_spans(raw + b" ", snapshot, requests=()))


def test_original_minimal_style_fixture_still_maps_under_new_fixed_profile():
    raw, _ = fixture(body=styled("Синтетический текст"))
    snapshot = build(raw)
    assert snapshot.complete and snapshot.profile == PROFILE and len(snapshot.lists) == 1
    original(raw, snapshot)


@pytest.mark.parametrize("maximum", (1, 100, 1000))
def test_auxiliary_raw_nodes_are_bounded_before_success(maximum):
    limits = replace(api().VisibleLimits(), max_xml_nodes=maximum)
    error("view_limit_exceeded", lambda: build(source(), limits=limits))


@pytest.mark.parametrize("case", ("plain", "numbered"))
def test_numbering_alternate_content_retains_physical_original_addresses(case):
    entries = parts(source(case))
    raw = entries["word/numbering.xml"].decode()

    def wrap(match):
        return (
            '<mc:AlternateContent xmlns:x="urn:unproved-future">'
            '<mc:Choice Requires="x"><x:unread/></mc:Choice>'
            "<mc:Fallback>" + match.group() + "</mc:Fallback></mc:AlternateContent>"
        )

    entries["word/numbering.xml"] = re.sub(
        r"<w:abstractNum .*?</w:abstractNum>", wrap, raw, flags=re.DOTALL
    ).encode()
    data = repack(entries)
    snapshot = build(data)
    assert snapshot.complete
    assert all(len(item.definition_anchor.path) >= 4 for item in snapshot.lists)
    original(data, snapshot)
    assert any(
        c.code == "compatibility_alternate_selection" and c.part_name == "word/numbering.xml"
        for c in snapshot.coverage
    )


@pytest.mark.parametrize("value", (None, "0", "1", "true", "false", "on", "off"))
def test_direct_contextual_spacing_changes_layout_not_literal_evidence(value):
    def spacing(root):
        paragraph = next(root.iter(W + "p"))
        properties = paragraph.find(W + "pPr")
        if properties is None:
            properties = ET.Element(W + "pPr")
            paragraph.insert(0, properties)
        ET.SubElement(
            properties, W + "contextualSpacing", {} if value is None else {W + "val": value}
        )

    raw = alter(source(), "word/document.xml", spacing)
    snapshot = build(raw)
    assert snapshot.complete
    assert snapshot.analysis_text == build(source()).analysis_text
    original(raw, snapshot)


def test_unknown_mandatory_numbering_namespace_refuses():
    entries = parts(source("numbered"))
    entries["word/numbering.xml"] = entries["word/numbering.xml"].replace(
        b"<w:numbering ", b'<w:numbering xmlns:x="urn:unproved-future" mc:MustUnderstand="x" ', 1
    )
    blocked(repack(entries))


def test_auxiliary_text_is_not_a_successful_empty_analysis():
    def text(root):
        root.text = "Unproved requirements text"

    blocked(alter(source(), "word/fontTable.xml", text))


@pytest.mark.parametrize(
    "part",
    (
        "word/fontTable.xml",
        "word/webSettings.xml",
        "word/theme/theme1.xml",
        "word/stylesWithEffects.xml",
        "customXml/itemProps1.xml",
    ),
)
def test_review_auxiliary_outgoing_edges_refuse(part):
    entries = parts(source())
    parent, _, name = part.rpartition("/")
    entries[parent + "/_rels/" + name + ".rels"] = (
        '<Relationships xmlns="' + REL[1:-1] + '"><Relationship Id="Unproved" '
        'Type="urn:unproved" TargetMode="External" Target="https://invalid.example/never-fetch"/>'
        "</Relationships>"
    ).encode()
    blocked(repack(entries))


@pytest.mark.parametrize(
    "part", ("word/fontTable.xml", "word/webSettings.xml", "word/theme/theme1.xml")
)
def test_review_unknown_metadata_attributes_refuse(part):
    blocked(alter(source(), part, lambda root: root.set("unproved", "1")))


def test_review_bibliography_properties_schema_conflict_refuses():
    ds = "{http://schemas.openxmlformats.org/officeDocument/2006/customXml}"

    def mismatch(root):
        root[0][0].set(ds + "uri", "urn:unknown")

    blocked(alter(source(), "customXml/itemProps1.xml", mismatch))


def test_review_base_default_missing_from_effects_refuses():
    def missing(root):
        root.remove(next(n for n in root if n.get(W + "styleId") == "Normal"))

    blocked(alter(source(), "word/stylesWithEffects.xml", missing))


def test_review_non_xml_whitespace_is_not_metadata_indentation():
    blocked(alter(source(), "word/fontTable.xml", lambda root: setattr(root, "text", "\u00a0")))


def test_review_new_profile_mapper_rejects_old_snapshot_type():
    from ara.docx_analysis.visible_style_lists import build_style_list_snapshot

    raw, _ = fixture()
    old = build_style_list_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert old.complete
    error("invalid_snapshot", lambda: api().map_word_spans(raw, old, requests=()))


def test_review_numbering_physical_anchor_forgery_refuses_even_empty_mapping():
    raw = source("numbered")
    snapshot = build(raw)
    item = snapshot.lists[0]
    fake = replace(item.definition_anchor, path=(0,))
    forged = rehash(
        replace(snapshot, lists=(replace(item, definition_anchor=fake), *snapshot.lists[1:]))
    )
    error("invalid_snapshot", lambda: api().map_word_spans(raw, forged, requests=()))


def test_review_inactive_numbering_branch_counts_against_raw_quota():
    from ara.docx_analysis.visible_style_lists import build_style_list_snapshot

    raw, _ = fixture()
    entries = parts(raw)
    part = next(p for p in entries if p.endswith("Numbers.xml"))
    xml = entries[part].decode()
    start = xml.index("<w:abstractNum ")
    end = xml.index("</w:abstractNum>", start) + len("</w:abstractNum>")
    entries[part] = (
        xml[:start] + "<mc:AlternateContent "
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:x="urn:future">'
        '<mc:Choice Requires="x">'
        + "<x:item/>" * 300
        + "</mc:Choice><mc:Fallback>"
        + xml[start:end]
        + "</mc:Fallback></mc:AlternateContent>"
        + xml[end:]
    ).encode()
    bounded = replace(api().VisibleLimits(), max_xml_nodes=200)
    # The ordinary minimal fixture fits; only the inactive raw branch exceeds this budget.
    assert build_style_list_snapshot(
        raw,
        document_id=DOC,
        storage_revision=7,
        source_sha256=sha256(raw).hexdigest(),
        limits=bounded,
    ).complete
    error("view_limit_exceeded", lambda: build(repack(entries), limits=bounded))


def test_review_unknown_package_root_image_role_cannot_be_excluded_as_unused_media():
    from test_docx_visible_inline_images import JPEG_BASELINE

    entries = parts(source())
    entries["docProps/thumbnail.jpeg"] = JPEG_BASELINE

    def wrong(root):
        link = next(n for n in root if n.get("Type").endswith("/thumbnail"))
        link.set("Type", "urn:unproved-root-role")

    blocked(alter(repack(entries), "_rels/.rels", wrong))
