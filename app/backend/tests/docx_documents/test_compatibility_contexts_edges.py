"""Source authority, old API compatibility, atomicity and pre-DOM quotas."""

import json
import os
import subprocess
import sys
from dataclasses import asdict
from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_compatibility_catalog import MAIN, alternate, choice
from test_docx_compatibility_contexts import api, blocked, catalogs, fixture, part_xml, read
from test_docx_note_catalog import note
from test_docx_section_catalog import BASE, section
from test_docx_visibility_styles import style

from ara.docx_analysis.visibility import StyleContextLimits
from ara.docx_analysis.visible_main import VisibleLimits, VisibleViewError


def error(code, call):
    with pytest.raises(VisibleViewError) as caught:
        call()
    assert caught.value.code == code


def old_catalogs(raw):
    kw = {"source_sha256": sha256(raw).hexdigest()}
    return (
        import_module("ara.docx_analysis.visibility").read_style_context(raw, **kw),
        import_module("ara.docx_analysis.table_styles").read_table_style_catalog(raw, **kw),
        import_module("ara.docx_analysis.sections").read_section_catalog(raw, **kw),
        import_module("ara.docx_analysis.notes").read_note_catalog(raw, **kw),
    )


def normalized(value):
    result = asdict(value)
    for name in ("profile", "catalog_sha256", "context_sha256", "style_context_sha256"):
        result.pop(name, None)
    return result


def test_plain_source_matches_old_catalog_semantics_except_explicit_profile_hashes():
    raw, _ = fixture(section(), styles=style("A"), settings="", foot=note())
    before = old_catalogs(raw)
    c = read(raw)
    assert c.status == "ready"
    assert [normalized(x) for x in catalogs(c)] == [normalized(x) for x in before]
    assert old_catalogs(raw) == before
    assert [x.profile for x in before] != [x.profile for x in catalogs(c)]


def test_new_selected_path_does_not_change_old_public_mc_refusals():
    raw, _ = fixture(
        alternate(choice("w", section())),
        styles=alternate(choice("w", style("A"))),
        foot=alternate(choice("w", note())),
    )
    before = old_catalogs(raw)
    assert all(x.status == "blocked" for x in before)
    assert read(raw).status == "ready"
    assert old_catalogs(raw) == before


def test_every_semantic_catalog_uses_one_view_without_legacy_dom_reparse(monkeypatch):
    api()
    module = import_module("ara.docx_analysis.compatibility_view._project")
    original, calls = module.build_tree, []
    raw, _ = fixture(section(), styles=alternate(choice("w", style("A"))), settings="", foot=note())

    def counted(*a, **kw):
        calls.append(a[1])
        return original(*a, **kw)

    def forbidden(*a, **kw):
        raise AssertionError("Legacy semantic tree bypassed the selected source view")

    monkeypatch.setattr(module, "build_tree", counted)
    for name, attr in (
        ("visibility._read", "parse"),
        ("table_styles._read", "parse"),
        ("sections._xml", "build_tree"),
        ("notes._xml", "build_tree"),
    ):
        monkeypatch.setattr(import_module("ara.docx_analysis." + name), attr, forbidden)
    c = read(raw)
    assert c.status == "ready" and calls == [
        "custom/Foot.xml",
        MAIN,
        "custom/Settings.xml",
        "custom/Styles.xml",
    ]


def test_raw_style_bounds_include_discarded_and_ambiguous_candidates_before_dom(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw style budgets")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    content = alternate(choice("x", style("A")) + choice("w", style("B")))
    raw = fixture(styles=content)[0]
    for caps in (
        StyleContextLimits(max_styles=1),
        StyleContextLimits(max_nodes=3),
        StyleContextLimits(max_depth=3),
    ):
        error("view_limit_exceeded", lambda caps=caps: read(raw, limits=VisibleLimits(styles=caps)))
    raw = fixture(
        styles=style("A"),
        extras={"custom/Z.xml": part_xml("styles", style("B") + style("C"))},
        types={"custom/Z.xml": BASE + "styles+xml"},
    )[0]
    error(
        "view_limit_exceeded",
        lambda: read(raw, limits=VisibleLimits(styles=StyleContextLimits(max_styles=2))),
    )


def test_raw_sections_notes_fields_and_controls_precede_any_view_dom(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("DOM before original semantic quotas")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    error("view_limit_exceeded", lambda: read(fixture("<w:sectPr/>" * 4097)[0]))
    error(
        "view_limit_exceeded",
        lambda: read(fixture(foot='<w:footnote w:id="2"><w:p/></w:footnote>' * 10001)[0]),
    )
    for content in ('<w:fldSimple w:instr="x"/><w:fldSimple w:instr="x"/>', "<w:sdt/><w:sdt/>"):
        raw = fixture(header=content)[0]
        error("view_limit_exceeded", lambda: read(raw, limits=VisibleLimits(max_pieces=1)))


def test_selected_style_chain_depth_remains_a_real_semantic_budget():
    content = alternate(choice("w", style("A") + style("B", '<w:basedOn w:val="A"/>')))
    raw = fixture(styles=content)[0]
    assert read(raw).status == "ready"
    error(
        "view_limit_exceeded",
        lambda: read(raw, limits=VisibleLimits(styles=StyleContextLimits(max_chain_depth=1))),
    )


def test_whole_bundle_manifest_has_exact_inclusive_size_limit():
    raw = fixture(styles=style("A"), foot=note())[0]
    c = read(raw)
    size = len(
        json.dumps(asdict(c), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    )
    assert read(raw, limits=VisibleLimits(max_manifest_bytes=size)) == c
    error(
        "view_limit_exceeded", lambda: read(raw, limits=VisibleLimits(max_manifest_bytes=size - 1))
    )


@pytest.mark.parametrize("body", ["", "<w:body/><w:body/>"])
def test_invalid_original_main_shape_keeps_package_error(body):
    from ara.docx_package import DocxError

    raw = fixture(extras={MAIN: part_xml("document", body)})[0]
    with pytest.raises(DocxError) as caught:
        read(raw)
    assert caught.value.code == "invalid_package"


def test_extra_selected_logical_body_refuses_after_valid_original_package():
    body = "<w:body/>" + alternate(choice("w", "<w:body/>"))
    raw = fixture(extras={MAIN: part_xml("document", body)})[0]
    blocked(raw)


def test_view_refusals_are_atomic_before_any_context_is_exposed():
    raw = fixture(
        "<x:keep>mixed<w:p/></x:keep>", attrs='mc:Ignorable="x" mc:ProcessContent="x:keep"'
    )[0]
    assert blocked(raw).issues[0].code == "unsupported_compatibility_text_boundary"
    raw = fixture("<w:p/>", attrs='mc:MustUnderstand="x"')[0]
    assert blocked(raw).issues[0].code == "unsupported_compatibility_requirement"


def test_exact_inputs_limits_and_source_pin():
    raw = fixture()[0]
    for value in (None, bytearray(raw), "bad"):
        error(
            "invalid_input",
            lambda value=value: api().read_compatibility_contexts(
                value, source_sha256=sha256(raw).hexdigest()
            ),
        )
    error("invalid_input", lambda: api().read_compatibility_contexts(raw, source_sha256="A" * 64))
    error("source_mismatch", lambda: api().read_compatibility_contexts(raw, source_sha256="0" * 64))
    error("invalid_input", lambda: read(raw, limits={}))
    caps = VisibleLimits()
    object.__setattr__(caps, "max_xml_depth", True)
    error("invalid_input", lambda: read(raw, limits=caps))
    with pytest.raises(TypeError):
        read(raw, view={})


def test_archive_size_precedes_hashing(monkeypatch):
    from ara.docx_package import DocxError

    api()

    def forbidden(*a, **kw):
        raise AssertionError("Hash before archive size validation")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_contexts._read"), "sha256", forbidden
    )
    with pytest.raises(DocxError) as caught:
        api().read_compatibility_contexts(b"x" * 33554433, source_sha256="0" * 64)
    assert caught.value.code == "package_limit_exceeded"


def test_public_contexts_do_not_retain_document_text_xml_or_private_reprs():
    raw = fixture("<w:p><w:r><w:t>PRIVATE-BODY</w:t></w:r></w:p>", styles=style("PRIVATE-STYLE"))[0]
    c = read(raw)
    assert c.status == "ready" and "PRIVATE-BODY" not in json.dumps(asdict(c))
    assert "PRIVATE-STYLE" not in repr(c) + repr(catalogs(c))
    assert not hasattr(c, "view") and not hasattr(c, "_original") and not hasattr(c, "__dict__")


def test_fresh_process_uses_only_given_bytes_and_no_application_io():
    raw = fixture(styles=alternate(choice("w", style("A"))), foot=alternate(choice("w", note())))[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O or XML output")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=ET.tostring=forbidden
from ara.docx_analysis.compatibility_contexts import read_compatibility_contexts
c=read_compatibility_contexts(data,source_sha256=sha256(data).hexdigest())
assert c.status=="ready" and c.styles.styles[0].style_id=="A" and c.notes.parts[0].linked
assert not hasattr(c,"complete") and not hasattr(c,"analysis_text")
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        timeout=30,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""


def test_other_word_namespace_body_cannot_hide_as_unknown_root_metadata():
    from test_docx_visible_main import S

    body = "<w:body/>" + f'<s:body xmlns:s="{S}"/>'
    c = blocked(fixture(extras={MAIN: part_xml("document", body)})[0])
    assert c.issues[0].code == "invalid_compatibility_main_root"


def test_external_styles_link_is_not_followed_or_treated_as_local_authority():
    from test_docx_visible_main import R

    raw = fixture(
        styles=style("A"),
        links=[
            {
                "Id": "external",
                "Type": R + "styles",
                "Target": "https://example.invalid/Styles.xml",
                "TargetMode": "External",
            }
        ],
    )[0]
    c = blocked(raw)
    assert c.issues[0].code == "ambiguous_styles_part"


def test_selected_unknown_base_style_is_retained_as_unresolved_not_fabricated():
    c = read(fixture(styles=alternate(choice("w", style("A", '<w:basedOn w:val="Missing"/>'))))[0])
    assert c.status == "ready" and c.styles.styles[0].status == "blocked"
    assert c.styles.styles[0].properties is None
    assert c.styles.styles[0].issues[0].code == "missing_base_style"


def test_unknown_word_settings_in_unselected_choice_do_not_duplicate_selected_flag():
    settings = alternate(
        choice("x", '<w:evenAndOddHeaders w:val="bad"/>')
        + choice("w", '<w:evenAndOddHeaders w:val="false"/>')
    )
    c = read(fixture(settings=settings)[0])
    assert c.status == "ready" and c.sections.even_and_odd is False


def test_unused_settings_candidates_cannot_evade_raw_section_budget(monkeypatch):
    api()

    def forbidden(*args, **kwargs):
        raise AssertionError("DOM before unused settings quota")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    raw = fixture(
        extras={"custom/UnusedSettings.xml": part_xml("settings", "<w:sectPr/>" * 4097)},
        types={"custom/UnusedSettings.xml": BASE + "settings+xml"},
    )[0]
    error("view_limit_exceeded", lambda: read(raw))


def test_c1_actions_and_items_respect_reader_piece_and_coverage_caps():
    raw = fixture('<w:p mc:Ignorable="x"/><w:p mc:Ignorable="x"/>')[0]
    error("view_limit_exceeded", lambda: read(raw, limits=VisibleLimits(max_coverage_items=1)))
    error("view_limit_exceeded", lambda: read(raw, limits=VisibleLimits(max_pieces=1)))
    assert read(raw).status == "ready"


def test_note_part_mime_and_relationship_kind_cannot_be_reassigned_by_projection():
    from test_docx_visible_main import R

    raw = fixture(
        foot=alternate(choice("w", note())),
        links=[{"Id": "Wrong", "Type": R + "endnotes", "Target": "Foot.xml"}],
    )[0]
    c = blocked(raw)
    assert c.issues[0].code == "unresolved_note_relationship"
