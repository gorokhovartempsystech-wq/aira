"""Independent D02-03 safety, conflict, limit and side-effect acceptance."""

import base64
import json
import subprocess
import sys
import traceback
from dataclasses import FrozenInstanceError, replace
from importlib import import_module
from pathlib import Path
from zipfile import ZIP_STORED

import pytest
from docx_package_fixtures import (
    WORD_NS,
    build_package,
    minimal_parts,
)
from docx_projection_fixtures import package, paragraph

ROOT = Path(__file__).resolve().parents[2]
MAIN = "word/document.xml"
PRIVATE = "SYNTHETIC_EDIT_PRIVATE_7903"
SETTINGS_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def api():
    return import_module("ara.docx_package.editing")


def projection_api():
    return import_module("ara.docx_package.projection")


def package_api():
    return import_module("ara.docx_package")


def plain(text=PRIVATE):
    return package(paragraph(text))[0]


def first_span(data):
    return projection_api().project_docx(data).blocks[0].spans[0]


def edit(data, replacement="Changed"):
    span = first_span(data)
    return api().TextEdit(span.anchor, span.text, replacement)


def reject(operation, exception_type, code):
    with pytest.raises(exception_type) as caught:
        operation()
    error = caught.value
    assert error.code == code
    assert isinstance(error.message, str) and error.message
    assert str(error) == error.message
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__
    assert PRIVATE not in str(error) + repr(error)
    assert PRIVATE not in "".join(traceback.format_exception(error))
    return error.message


def settings_package(markup, *, namespace=WORD_NS):
    payload = f'<w:settings xmlns:w="{namespace}">{markup}</w:settings>'.encode()
    return package(
        paragraph(PRIVATE),
        extra_parts={"custom/preferences.xml": payload},
        extra_types={"custom/preferences.xml": SETTINGS_TYPE},
    )[0]


def test_edits_container_and_elements_are_strict():
    module = api()
    data = plain()
    value = edit(data)
    for candidate in ([value], {"edit": value}, iter((value,)), value, None, (object(),)):
        reject(lambda: module.export_docx(data, candidate), module.EditError, "invalid_input")


def test_mutated_text_edit_fields_are_revalidated():
    module = api()
    data = plain()
    for field, value in (
        ("anchor", None),
        ("anchor", {}),
        ("expected_text", b"text"),
        ("expected_text", None),
        ("replacement_text", 7),
        ("replacement_text", [PRIVATE]),
    ):
        candidate = edit(data)
        object.__setattr__(candidate, field, value)
        reject(lambda: module.export_docx(data, (candidate,)), module.EditError, "invalid_input")


def test_anchor_shapes_are_revalidated_even_after_frozen_bypass():
    module = api()
    data = plain()
    for field, value in (
        ("source_sha256", "F" * 64),
        ("source_sha256", "a" * 63),
        ("source_sha256", PRIVATE),
        ("part_name", ""),
        ("part_name", None),
        ("path", [0, 0, 0, 0]),
        ("path", (True,)),
        ("path", (-1,)),
        ("path", (0.0,)),
        ("path", ("0",)),
    ):
        candidate = edit(data)
        object.__setattr__(candidate.anchor, field, value)
        reject(lambda: module.export_docx(data, (candidate,)), module.EditError, "invalid_input")


def test_text_edit_is_frozen_slotted_and_does_not_print_user_text():
    module = api()
    data = plain()
    value = edit(data, PRIVATE + "_replacement")
    assert PRIVATE not in repr(value)
    assert not hasattr(value, "__dict__")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        value.expected_text = "other"
    limits = module.EditLimits()
    assert not hasattr(limits, "__dict__")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        limits.max_edits = 9
    assert (limits.max_edits, limits.max_total_replacement_chars) == (1000, 1000000)


@pytest.mark.parametrize("field", ["max_edits", "max_total_replacement_chars"])
def test_edit_limits_reject_non_positive_or_coerced_integers(field):
    module = api()
    for value in (0, -1, True, 1.0, "1", None):
        reject(lambda: module.EditLimits(**{field: value}), module.EditError, "invalid_input")
        limits = module.EditLimits()
        object.__setattr__(limits, field, value)
        reject(
            lambda: module.export_docx(plain(), (), edit_limits=limits),
            module.EditError,
            "invalid_input",
        )


def test_foreign_limit_objects_are_not_coerced():
    module = api()
    data = plain()
    for value in ({}, True, 1, object(), package_api().DocxLimits()):
        reject(
            lambda: module.export_docx(data, (), edit_limits=value),
            module.EditError,
            "invalid_input",
        )


def test_source_hash_conflict_is_distinct_and_applies_to_noop():
    module = api()
    original = plain()
    other = package(paragraph(PRIVATE), comment=b"different source bytes")[0]
    candidate = edit(original, PRIVATE)
    reject(lambda: module.export_docx(other, (candidate,)), module.EditError, "stale_source")
    exported = module.export_docx(original, (edit(original),))
    reject(
        lambda: module.export_docx(exported, (edit(original),)),
        module.EditError,
        "stale_source",
    )


def test_anchor_must_target_existing_main_body_text_span():
    module = api()
    data = plain()
    original = first_span(data).anchor
    for anchor in (
        replace(original, path=()),
        replace(original, path=(0,)),
        replace(original, path=(0, 0)),
        replace(original, path=(0, 0, 0)),
        replace(original, path=(0, 99, 0, 0)),
        replace(original, part_name="word/header1.xml"),
        replace(original, part_name="/word/document.xml"),
    ):
        reject(
            lambda: module.export_docx(data, (module.TextEdit(anchor, PRIVATE, "Changed"),)),
            module.EditError,
            "invalid_anchor",
        )


def test_existing_properties_tabs_breaks_and_opaque_spans_are_not_editable():
    module = api()
    data = package(
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        "<w:r><w:rPr><w:b/></w:rPr><w:t>Visible</w:t><w:tab/><w:br/>"
        "<w:drawing><s:hidden/></w:drawing></w:r></w:p>"
    )[0]
    projection = projection_api().project_docx(data)
    para = projection.blocks[0]
    targets = [(para.properties_anchor, "")] + [
        (span.anchor, span.text) for span in para.spans if span.kind != "text"
    ]
    for anchor, expected in targets:
        reject(
            lambda: module.export_docx(data, (module.TextEdit(anchor, expected, "Changed"),)),
            module.EditError,
            "invalid_anchor",
        )


@pytest.mark.parametrize(
    "body,path",
    [
        ("<w:p><w:ins><w:r><w:t>Hidden</w:t></w:r></w:ins></w:p>", (0, 0, 0, 0, 0)),
        ('<w:p><w:r><w:fldChar w:fldCharType="begin"/><w:t>Hidden</w:t></w:r></w:p>', (0, 0, 0, 1)),
        (
            "<w:p><w:r><w:fldSimple><w:r><w:t>Hidden</w:t></w:r></w:fldSimple></w:r></w:p>",
            (0, 0, 0, 0, 0, 0),
        ),
        ("<s:wrapper><w:p><w:r><w:t>Hidden</w:t></w:r></w:p></s:wrapper>", (0, 0, 0, 0, 0)),
    ],
)
def test_hidden_text_cannot_be_edited_by_forging_an_xml_address(body, path):
    module = api()
    data = package(body)[0]
    projection = projection_api().project_docx(data)
    anchor = projection_api().SourceAnchor(projection.source.sha256, MAIN, path)
    reject(
        lambda: module.export_docx(data, (module.TextEdit(anchor, "Hidden", "Changed"),)),
        module.EditError,
        "invalid_anchor",
    )
    assert module.export_docx(data, ()) == data


def test_expected_text_matching_is_exact_and_not_unicode_normalized():
    module = api()
    data = plain(" caf\u00e9 ")
    anchor = first_span(data).anchor
    for expected in ("caf\u00e9", " cafe\u0301 ", " caf\u00e9", "wrong"):
        reject(
            lambda: module.export_docx(data, (module.TextEdit(anchor, expected, "Changed"),)),
            module.EditError,
            "text_mismatch",
        )


def test_duplicate_edits_fail_even_when_identical_or_noop():
    module = api()
    data = plain()
    changed, noop = edit(data), edit(data, PRIVATE)
    for candidates in ((changed, changed), (changed, noop), (noop, noop)):
        reject(lambda: module.export_docx(data, candidates), module.EditError, "duplicate_edit")


def test_invalid_later_edit_aborts_whole_batch_and_keeps_original_usable():
    module = api()
    data = package(paragraph("First") + paragraph("Second"))[0]
    projection = projection_api().project_docx(data)
    first, second = (block.spans[0] for block in projection.blocks)
    candidates = (
        module.TextEdit(first.anchor, "First", "New first"),
        module.TextEdit(second.anchor, "wrong", "New second"),
    )
    before = bytes(data)
    reject(lambda: module.export_docx(data, candidates), module.EditError, "text_mismatch")
    assert data == before
    assert [b.text for b in projection_api().project_docx(data).blocks] == ["First", "Second"]
    exported = module.export_docx(data, (candidates[0],))
    assert [b.text for b in projection_api().project_docx(exported).blocks] == [
        "New first",
        "Second",
    ]


def test_replacement_rejects_invalid_xml_characters_without_disclosing_text():
    module = api()
    data = plain()
    messages = set()
    for char in ("\0", "\x01", "\x0b", "\x0c", "\x1f", "\ud800", "\udfff", "\ufffe", "\uffff"):
        messages.add(
            reject(
                lambda: module.export_docx(data, (edit(data, PRIVATE + char),)),
                module.EditError,
                "invalid_input",
            )
        )
    assert len(messages) == 1


@pytest.mark.parametrize("control", ["\t", "\r", "\n"])
def test_new_word_control_characters_are_not_silently_flattened(control):
    module = api()
    data = plain()
    reject(
        lambda: module.export_docx(data, (edit(data, "New" + control + "line"),)),
        module.EditError,
        "unsupported_edit",
    )


def test_noop_can_retain_existing_normalized_newlines_and_tabs():
    module = api()
    data = package("<w:p><w:r><w:t>one&#13;two&#10;three&#9;four</w:t></w:r></w:p>")[0]
    span = first_span(data)
    assert span.text == "one\rtwo\nthree\tfour"
    assert module.export_docx(data, (module.TextEdit(span.anchor, span.text, span.text),)) == data


@pytest.mark.parametrize("inner", ["old<!--retain me-->text", "old<?keep value?>text"])
def test_comments_and_processing_instructions_in_target_prevent_actual_replacement(inner):
    module = api()
    data = package(f"<w:p><w:r><w:t>{inner}</w:t></w:r></w:p>")[0]
    span = first_span(data)
    assert span.text == "oldtext"
    reject(
        lambda: module.export_docx(data, (module.TextEdit(span.anchor, span.text, "new"),)),
        module.EditError,
        "unsupported_edit",
    )
    assert module.export_docx(data, (module.TextEdit(span.anchor, span.text, span.text),)) == data


def test_other_valid_encoding_preserves_noop_and_never_corrupts_changed_text():
    module = api()
    data = package(paragraph("caf\u00e9"), encoding="iso-8859-1")[0]
    span = first_span(data)
    assert module.export_docx(data, (module.TextEdit(span.anchor, span.text, span.text),)) == data
    try:
        exported = module.export_docx(data, (module.TextEdit(span.anchor, span.text, "new"),))
    except module.EditError as error:
        assert error.code == "unsupported_edit"
    else:
        assert projection_api().project_docx(exported).blocks[0].text == "new"


@pytest.mark.parametrize("marker", ["part_name", "content_type", "relationship"])
def test_signature_markers_block_mutation_but_allow_exact_noop(marker):
    module = api()
    parts = {"custom/signature.xml": b"<signature/>"}
    types = {}
    links = ()
    if marker == "part_name":
        parts = {"_XMLSIGNATURES/hidden.xml": b"<signature/>"}
    elif marker == "content_type":
        types = {
            "custom/signature.xml": (
                "application/vnd.openxmlformats-package.digital-signature-xmlsignature+xml"
            )
        }
    else:
        links = (
            {
                "Id": "rSignature",
                "Type": "http://schemas.openxmlformats.org/package/2006/relationships/digital-signature/signature",
                "Target": "../custom/signature.xml",
            },
        )
    data = package(paragraph(PRIVATE), extra_parts=parts, extra_types=types, links=links)[0]
    reject(lambda: module.export_docx(data, (edit(data),)), module.EditError, "unsupported_edit")
    assert module.export_docx(data, ()) == data
    assert module.export_docx(data, (edit(data, PRIVATE),)) == data


@pytest.mark.parametrize(
    "markup",
    [
        "<w:documentProtection/>",
        '<w:documentProtection w:enforcement="false"/>',
        "<w:trackRevisions/>",
        '<w:trackRevisions w:val="1"/>',
        '<w:trackRevisions w:val="unrecognized"/>',
        '<w:trackRevisions w:val="0"/><w:trackRevisions w:val="false"/>',
        '<s:wrapper xmlns:s="urn:synthetic"><w:trackRevisions/></s:wrapper>',
    ],
)
def test_settings_prevent_mutations_without_silently_changing_review_policy(markup):
    module = api()
    data = settings_package(markup)
    reject(lambda: module.export_docx(data, (edit(data),)), module.EditError, "unsupported_edit")
    assert module.export_docx(data, (edit(data, PRIVATE),)) == data


def test_explicitly_disabled_tracking_and_foreign_namespace_markers_do_not_block():
    module = api()
    for value in ("0", "false", "off"):
        data = settings_package(f'<w:trackRevisions w:val="{value}"/>')
        result = module.export_docx(data, (edit(data),))
        assert projection_api().project_docx(result).blocks[0].text == "Changed"
    data = settings_package(
        '<f:documentProtection xmlns:f="urn:foreign"/><f:trackRevisions xmlns:f="urn:foreign"/>'
    )
    result = module.export_docx(data, (edit(data),))
    assert projection_api().project_docx(result).blocks[0].text == "Changed"


@pytest.mark.parametrize("case", ["multiple", "external", "wrong_type", "wrong_root"])
def test_ambiguous_settings_or_invalid_relationship_target_prevent_mutation(case):
    module = api()
    settings = f'<w:settings xmlns:w="{WORD_NS}"/>'.encode()
    parts = {"custom/preferences.xml": settings}
    types = {"custom/preferences.xml": SETTINGS_TYPE}
    links = ()
    if case == "multiple":
        parts["custom/second.xml"] = settings
        types["custom/second.xml"] = SETTINGS_TYPE
    elif case == "external":
        parts, types = {}, {}
        links = (
            {
                "Id": "rSettings",
                "Type": REL_NS + "/settings",
                "Target": "https://example.invalid/settings",
                "TargetMode": "External",
            },
        )
    elif case == "wrong_type":
        types = {}
        links = (
            {
                "Id": "rSettings",
                "Type": REL_NS + "/settings",
                "Target": "../custom/preferences.xml",
            },
        )
    else:
        parts["custom/preferences.xml"] = b'<settings xmlns="urn:foreign"/>'
    data = package(paragraph(PRIVATE), extra_parts=parts, extra_types=types, links=links)[0]
    reject(lambda: module.export_docx(data, (edit(data),)), module.EditError, "unsupported_edit")
    assert module.export_docx(data, (edit(data, PRIVATE),)) == data


def test_one_settings_part_referenced_by_type_and_relationship_is_not_ambiguous():
    module = api()
    for relationship in (
        REL_NS + "/settings",
        "http://purl.oclc.org/ooxml/officeDocument/relationships/settings",
    ):
        data = package(
            paragraph(PRIVATE),
            extra_parts={"custom/preferences.xml": f'<w:settings xmlns:w="{WORD_NS}"/>'.encode()},
            extra_types={"custom/preferences.xml": SETTINGS_TYPE},
            links=(
                {"Id": "rSettings", "Type": relationship, "Target": "../custom/preferences.xml"},
            ),
        )[0]
        exported = module.export_docx(data, (edit(data),))
        assert first_span(exported).text == "Changed"


def test_edit_count_limit_includes_noops_and_boundary_is_inclusive():
    module = api()
    data = package(paragraph("One") + paragraph("Two"))[0]
    spans = [block.spans[0] for block in projection_api().project_docx(data).blocks]
    candidates = tuple(module.TextEdit(span.anchor, span.text, span.text) for span in spans)
    reject(
        lambda: module.export_docx(data, candidates, edit_limits=module.EditLimits(max_edits=1)),
        module.EditError,
        "edit_limit_exceeded",
    )
    assert module.export_docx(data, candidates, edit_limits=module.EditLimits(max_edits=2)) == data


def test_replacement_budget_counts_unicode_codepoints_and_includes_noops():
    module = api()
    data = plain("old")
    value = edit(data, "\U0001f600\u00e9")
    result = module.export_docx(
        data, (value,), edit_limits=module.EditLimits(max_total_replacement_chars=2)
    )
    assert first_span(result).text == "\U0001f600\u00e9"
    reject(
        lambda: module.export_docx(
            data, (value,), edit_limits=module.EditLimits(max_total_replacement_chars=1)
        ),
        module.EditError,
        "edit_limit_exceeded",
    )
    reject(
        lambda: module.export_docx(
            data, (edit(data, "old"),), edit_limits=module.EditLimits(max_total_replacement_chars=2)
        ),
        module.EditError,
        "edit_limit_exceeded",
    )


def test_existing_package_and_projection_validation_still_applies_to_empty_edits():
    module = api()
    for value in (None, "not bytes", bytearray(b"bad")):
        reject(lambda: module.export_docx(value, ()), package_api().DocxError, "invalid_input")
    reject(
        lambda: module.export_docx(PRIVATE.encode(), ()),
        package_api().DocxError,
        "invalid_package",
    )
    reject(
        lambda: module.export_docx(plain(), (), limits={}),
        package_api().DocxError,
        "invalid_input",
    )
    reject(
        lambda: module.export_docx(plain(), (), projection_limits={}),
        projection_api().ProjectionError,
        "invalid_input",
    )
    reject(
        lambda: module.export_docx(
            plain(), (), projection_limits=projection_api().ProjectionLimits(max_nodes=1)
        ),
        projection_api().ProjectionError,
        "projection_limit_exceeded",
    )


@pytest.mark.parametrize(
    "field",
    ["max_xml_bytes", "max_part_bytes", "max_total_uncompressed_bytes", "max_archive_bytes"],
)
def test_grown_export_is_validated_against_original_package_limits(field):
    module = api()
    parts = minimal_parts()
    parts[MAIN] = package(paragraph("old"))[1]
    data = build_package(parts, compression=ZIP_STORED)
    if field == "max_archive_bytes":
        bound = len(data)
    elif field == "max_total_uncompressed_bytes":
        bound = sum(len(payload) for payload in parts.values())
    else:
        bound = max(len(payload) for payload in parts.values())
    limits = package_api().DocxLimits(**{field: bound})
    assert module.export_docx(data, (), limits=limits) == data
    reject(
        lambda: module.export_docx(data, (edit(data, "X&<" * 3000),), limits=limits),
        package_api().DocxError,
        "package_limit_exceeded",
    )


def test_safe_error_messages_are_constant_for_different_client_text():
    module = api()
    data = plain()
    anchor = first_span(data).anchor
    messages = {
        reject(
            lambda: module.export_docx(data, (module.TextEdit(anchor, expected, PRIVATE),)),
            module.EditError,
            "text_mismatch",
        )
        for expected in (PRIVATE + "X", "a completely different input")
    }
    assert len(messages) == 1


def test_import_and_editing_operations_do_not_access_external_resources_or_log():
    api()
    data = package(
        paragraph(PRIVATE),
        links=(
            {
                "Id": "rExternal",
                "Type": REL_NS + "/hyperlink",
                "Target": "https://example.invalid/synthetic-edit",
                "TargetMode": "External",
            },
        ),
    )[0]
    code = """
import base64, builtins, importlib, io, json, logging, os, socket, subprocess, tempfile
from pathlib import Path
import urllib.request, zipfile, dataclasses, hashlib, copy, re, struct, codecs
from xml.etree import ElementTree
import xml.parsers.expat
import psycopg, sqlalchemy
import ara.config, ara.db
import ara.docx_package.projection as projection
raw = base64.b64decode(PAYLOAD)
span = projection.project_docx(raw).blocks[0].spans[0]
names = ['ara.docx_package.editing'] + [
    '.'.join(p.with_suffix('').parts[1:])
    for p in sorted(Path('src/ara/docx_package/editing').rglob('*.py'))
    if p.name != '__init__.py'
]
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external I/O or logging in editing')
for target, name in (
    (builtins, 'open'), (io, 'open'), (Path, 'open'), (Path, 'read_text'), (Path, 'read_bytes'),
    (Path, 'write_text'), (Path, 'write_bytes'), (Path, 'mkdir'), (os, 'open'), (os, 'mkdir'),
    (os, 'system'), (os, 'popen'), (socket, 'socket'), (socket, 'create_connection'),
    (subprocess, 'Popen'), (subprocess, 'run'), (urllib.request, 'urlopen'),
    (tempfile, 'TemporaryFile'), (tempfile, 'NamedTemporaryFile'), (tempfile, 'mkdtemp'),
    (psycopg, 'connect'), (sqlalchemy, 'create_engine'), (ara.config, 'load_settings'),
    (ara.db, 'create_database_engine'), (logging.Logger, '_log'),
):
    setattr(target, name, forbidden)
for name in names:
    importlib.import_module(name)
module = importlib.import_module('ara.docx_package.editing')
value = module.TextEdit(span.anchor, span.text, 'Changed')
result = module.export_docx(raw, (value,))
assert projection.project_docx(result).blocks[0].text == 'Changed'
assert module.export_docx(raw, ()) == raw
try:
    module.export_docx(raw, (module.TextEdit(span.anchor, 'wrong', 'Changed'),))
except module.EditError as error:
    assert error.code == 'text_mismatch'
else:
    raise AssertionError('Expected text conflict was accepted')
""".replace("PAYLOAD", json.dumps(base64.b64encode(data).decode()))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "" and result.stderr == ""
