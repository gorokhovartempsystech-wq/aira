"""Independent range edit safety, ownership of boundaries and atomicity."""

import base64
import json
import subprocess
import sys
import traceback
from dataclasses import FrozenInstanceError, replace
from importlib import import_module
from pathlib import Path

import pytest
from docx_editing_fixtures import text_spans
from docx_package_fixtures import WORD_NS
from docx_projection_fixtures import package, paragraph

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "SYNTHETIC_RANGE_PRIVATE_4628"
SETTINGS_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"


def api():
    return import_module("ara.docx_package.ranges")


def projection_api():
    return import_module("ara.docx_package.projection")


def editing_api():
    return import_module("ara.docx_package.editing")


def package_api():
    return import_module("ara.docx_package")


def source(body=None, **kwargs):
    data = package(paragraph(PRIVATE) if body is None else body, **kwargs)[0]
    projection = projection_api().project_docx(data)
    return data, projection, text_spans(projection)


def make_edit(spans, start, end, expected, replacement):
    module = api()
    return module.RangeEdit(
        module.TextPosition(spans[start[0]].anchor, start[1]),
        module.TextPosition(spans[end[0]].anchor, end[1]),
        expected,
        replacement,
    )


def simple_edit(spans, replacement="Changed"):
    return make_edit(spans, (0, 0), (0, len(spans[0].text)), spans[0].text, replacement)


def reject(operation, exception_type, code):
    with pytest.raises(exception_type) as caught:
        operation()
    error = caught.value
    assert error.code == code
    assert isinstance(error.message, str) and error.message
    assert str(error) == error.message
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__
    rendered = str(error) + repr(error) + "".join(traceback.format_exception(error))
    assert PRIVATE not in rendered
    return error.message


def test_containers_and_edit_classes_are_not_coerced():
    module = api()
    data, _, spans = source()
    candidate = simple_edit(spans)
    for value in (None, [candidate], iter((candidate,)), {"edit": candidate}, (object(),)):
        reject(lambda: module.export_docx_ranges(data, value), module.RangeError, "invalid_input")


def test_dtos_are_frozen_slotted_and_range_repr_omits_text():
    module = api()
    _, _, spans = source()
    value = simple_edit(spans, PRIVATE + "_new")
    assert PRIVATE not in repr(value)
    for obj, field, other in (
        (value, "expected_text", "other"),
        (value.start, "offset", 1),
        (module.RangeLimits(), "max_edits", 1),
    ):
        assert not hasattr(obj, "__dict__")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            setattr(obj, field, other)
    limits = module.RangeLimits()
    assert (limits.max_edits, limits.max_total_replacement_chars, limits.max_touched_spans) == (
        1000,
        1000000,
        10000,
    )


def test_mutated_positions_ranges_and_anchors_are_revalidated():
    module = api()
    data, _, spans = source()
    for target, field, replacement in (
        ("range", "start", None),
        ("range", "end", {}),
        ("range", "expected_text", b"bytes"),
        ("range", "replacement_text", 1),
        ("start", "offset", True),
        ("start", "offset", -1),
        ("end", "offset", 1.0),
        ("end", "anchor", {}),
        ("anchor", "source_sha256", "F" * 64),
        ("anchor", "source_sha256", "a" * 63),
        ("anchor", "part_name", ""),
        ("anchor", "path", [0, 0, 0, 0]),
        ("anchor", "path", (False,)),
        ("anchor", "path", (-1,)),
    ):
        candidate = simple_edit(spans)
        # Copy the address: the fixture's authoritative projection must not be mutated.
        object.__setattr__(candidate.start, "anchor", replace(candidate.start.anchor))
        obj = {
            "range": candidate,
            "start": candidate.start,
            "end": candidate.end,
            "anchor": candidate.start.anchor,
        }[target]
        object.__setattr__(obj, field, replacement)
        reject(
            lambda: module.export_docx_ranges(data, (candidate,)),
            module.RangeError,
            "invalid_input",
        )


def test_deleted_slots_are_safe_input_errors():
    module = api()
    data, _, spans = source()
    for target, fields in (
        ("range", ("start", "end", "expected_text", "replacement_text")),
        ("start", ("anchor", "offset")),
        ("end", ("anchor", "offset")),
        ("anchor", ("source_sha256", "part_name", "path")),
    ):
        for field in fields:
            candidate = simple_edit(spans)
            object.__setattr__(candidate.start, "anchor", replace(candidate.start.anchor))
            obj = {
                "range": candidate,
                "start": candidate.start,
                "end": candidate.end,
                "anchor": candidate.start.anchor,
            }[target]
            object.__delattr__(obj, field)
            reject(
                lambda: module.export_docx_ranges(data, (candidate,)),
                module.RangeError,
                "invalid_input",
            )


@pytest.mark.parametrize("field", ["max_edits", "max_total_replacement_chars", "max_touched_spans"])
def test_range_limits_validate_constructor_mutation_and_missing_slots(field):
    module = api()
    data, _, _ = source()
    for value in (0, -1, True, 1.0, "1", None):
        reject(lambda: module.RangeLimits(**{field: value}), module.RangeError, "invalid_input")
        limits = module.RangeLimits()
        object.__setattr__(limits, field, value)
        reject(
            lambda: module.export_docx_ranges(data, (), range_limits=limits),
            module.RangeError,
            "invalid_input",
        )
    limits = module.RangeLimits()
    object.__delattr__(limits, field)
    reject(
        lambda: module.export_docx_ranges(data, (), range_limits=limits),
        module.RangeError,
        "invalid_input",
    )


def test_foreign_range_limits_are_not_coerced():
    module = api()
    data, _, _ = source()
    for value in ({}, True, 1, object(), editing_api().EditLimits()):
        reject(
            lambda: module.export_docx_ranges(data, (), range_limits=value),
            module.RangeError,
            "invalid_input",
        )


@pytest.mark.parametrize("endpoint", ["start", "end"])
def test_each_endpoint_checks_source_hash_before_allowing_noop(endpoint):
    module = api()
    data, _, spans = source()
    candidate = simple_edit(spans, PRIVATE)
    position = getattr(candidate, endpoint)
    object.__setattr__(position, "anchor", replace(position.anchor, source_sha256="0" * 64))
    reject(lambda: module.export_docx_ranges(data, (candidate,)), module.RangeError, "stale_source")
    exported = module.export_docx_ranges(data, (simple_edit(spans),))
    reject(
        lambda: module.export_docx_ranges(exported, (simple_edit(spans),)),
        module.RangeError,
        "stale_source",
    )


def test_anchors_must_be_projected_text_in_main_part():
    module = api()
    data, projection, spans = source(
        "<w:p><w:pPr/><w:r><w:t>Text</w:t><w:tab/><w:br/><w:drawing/></w:r></w:p>"
    )
    para = projection.blocks[0]
    anchors = [projection.body_anchor, para.anchor, para.properties_anchor]
    anchors.extend(span.anchor for span in para.spans if span.kind != "text")
    anchors.extend(
        (
            replace(spans[0].anchor, path=(0, 90)),
            replace(spans[0].anchor, part_name="word/header1.xml"),
        )
    )
    for anchor in anchors:
        candidate = module.RangeEdit(
            module.TextPosition(anchor, 0), module.TextPosition(anchor, 0), "", "x"
        )
        reject(
            lambda: module.export_docx_ranges(data, (candidate,)),
            module.RangeError,
            "invalid_anchor",
        )


def test_offsets_and_reverse_order_are_invalid_ranges_not_text_conflicts():
    module = api()
    data, _, spans = source("<w:p><w:r><w:t>A\U0001f600B</w:t><w:t>tail</w:t></w:r></w:p>")
    for start, end in (((0, 4), (0, 4)), ((0, 2), (0, 1)), ((1, 0), (0, 3))):
        candidate = make_edit(spans, start, end, "", "new")
        reject(
            lambda: module.export_docx_ranges(data, (candidate,)),
            module.RangeError,
            "invalid_range",
        )


def test_equal_absolute_positions_on_different_anchors_are_ambiguous():
    module = api()
    data, _, spans = source("<w:p><w:r><w:t>A</w:t><w:t/><w:t>B</w:t></w:r></w:p>")
    for start, end in (((0, 1), (1, 0)), ((0, 1), (2, 0)), ((1, 0), (2, 0))):
        candidate = make_edit(spans, start, end, "", "insert")
        reject(
            lambda: module.export_docx_ranges(data, (candidate,)),
            module.RangeError,
            "invalid_range",
        )


def test_ranges_cannot_cross_paragraphs_or_table_cells():
    module = api()
    for body in (
        paragraph("One") + paragraph("Two"),
        "<w:tbl><w:tr><w:tc>"
        + paragraph("One")
        + "</w:tc><w:tc>"
        + paragraph("Two")
        + "</w:tc></w:tr></w:tbl>",
    ):
        data, _, spans = source(body)
        candidate = make_edit(spans, (0, 0), (1, 1), "OneT", "new")
        reject(
            lambda: module.export_docx_ranges(data, (candidate,)),
            module.RangeError,
            "invalid_range",
        )


def test_expected_text_is_exact_including_unicode_and_insertion_empty_string():
    module = api()
    data, _, spans = source(paragraph(" caf\u00e9 "))
    messages = set()
    for expected in ("caf\u00e9", " cafe\u0301 ", PRIVATE):
        candidate = make_edit(spans, (0, 0), (0, 6), expected, "new")
        messages.add(
            reject(
                lambda: module.export_docx_ranges(data, (candidate,)),
                module.RangeError,
                "text_mismatch",
            )
        )
    assert len(messages) == 1
    candidate = make_edit(spans, (0, 2), (0, 2), "not empty", "new")
    reject(
        lambda: module.export_docx_ranges(data, (candidate,)), module.RangeError, "text_mismatch"
    )


@pytest.mark.parametrize("case", ["overlap", "duplicate", "inside", "left", "right", "same_insert"])
def test_conflicts_include_noops_and_insertion_boundaries_independent_of_order(case):
    module = api()
    data, _, spans = source(paragraph("abcdef"))
    first = make_edit(spans, (0, 1), (0, 4), "bcd", "bcd")
    second = {
        "overlap": make_edit(spans, (0, 3), (0, 5), "de", "X"),
        "duplicate": make_edit(spans, (0, 1), (0, 4), "bcd", "Y"),
        "inside": make_edit(spans, (0, 2), (0, 2), "", "X"),
        "left": make_edit(spans, (0, 1), (0, 1), "", "X"),
        "right": make_edit(spans, (0, 4), (0, 4), "", "X"),
        "same_insert": make_edit(spans, (0, 1), (0, 1), "", "Y"),
    }[case]
    if case == "same_insert":
        first = make_edit(spans, (0, 1), (0, 1), "", "")
    for candidates in ((first, second), (second, first)):
        reject(
            lambda: module.export_docx_ranges(data, candidates),
            module.RangeError,
            "conflicting_edits",
        )


def test_insertions_with_different_anchors_at_same_absolute_position_conflict():
    module = api()
    data, _, spans = source("<w:p><w:r><w:t>A</w:t><w:t>B</w:t></w:r></w:p>")
    first = make_edit(spans, (0, 1), (0, 1), "", "X")
    second = make_edit(spans, (1, 0), (1, 0), "", "Y")
    reject(
        lambda: module.export_docx_ranges(data, (first, second)),
        module.RangeError,
        "conflicting_edits",
    )


def test_adjacent_ranges_and_equal_offsets_in_different_paragraphs_do_not_conflict():
    module = api()
    data, _, spans = source(paragraph("abcdef") + paragraph("abcdef"))
    candidates = (
        make_edit(spans, (0, 0), (0, 3), "abc", "A"),
        make_edit(spans, (0, 3), (0, 6), "def", "B"),
        make_edit(spans, (1, 0), (1, 3), "abc", "C"),
    )
    result = module.export_docx_ranges(data, candidates)
    assert [b.text for b in projection_api().project_docx(result).blocks] == ["AB", "Cdef"]
    assert module.export_docx_ranges(data, tuple(reversed(candidates))) == result


@pytest.mark.parametrize(
    "middle,expected", [("<w:tab/>", "A\tB"), ("<w:br/>", "A\nB"), ("<w:drawing/>", "A\ufffcB")]
)
def test_unsupported_middle_spans_block_changes_but_allow_exact_noop(middle, expected):
    module = api()
    data, _, spans = source("<w:p><w:r><w:t>A</w:t>" + middle + "<w:t>B</w:t></w:r></w:p>")
    candidate = make_edit(spans, (0, 0), (1, 1), expected, "new")
    reject(
        lambda: module.export_docx_ranges(data, (candidate,)),
        module.RangeError,
        "unsupported_range",
    )
    noop = make_edit(spans, (0, 0), (1, 1), expected, expected)
    assert module.export_docx_ranges(data, (noop,)) == data


def test_revisions_and_complex_fields_do_not_become_range_endpoints():
    module = api()
    for body, path in (
        ("<w:p><w:ins><w:r><w:t>Hidden</w:t></w:r></w:ins></w:p>", (0, 0, 0, 0, 0)),
        ('<w:p><w:r><w:fldChar w:fldCharType="begin"/><w:t>Hidden</w:t></w:r></w:p>', (0, 0, 0, 1)),
    ):
        data, projection, _ = source(body)
        anchor = projection_api().SourceAnchor(projection.source.sha256, "word/document.xml", path)
        candidate = module.RangeEdit(
            module.TextPosition(anchor, 0), module.TextPosition(anchor, 6), "Hidden", "new"
        )
        reject(
            lambda: module.export_docx_ranges(data, (candidate,)),
            module.RangeError,
            "invalid_anchor",
        )
        assert module.export_docx_ranges(data, ()) == data


@pytest.mark.parametrize(
    "boundary",
    [
        "normal_to_link",
        "same_target_different_links",
        "empty_link",
        "end_at_zero",
        "start_at_length",
    ],
)
def test_hyperlink_identity_includes_empty_and_endpoint_spans(boundary):
    module = api()
    linked_a = '<w:hyperlink r:id="same"><w:r><w:t>A</w:t></w:r></w:hyperlink>'
    linked_b = '<w:hyperlink r:id="same"><w:r><w:t>B</w:t></w:r></w:hyperlink>'
    plain_a, plain_b = "<w:r><w:t>A</w:t></w:r>", "<w:r><w:t>B</w:t></w:r>"
    middle = '<w:hyperlink r:id="same"><w:r><w:t/></w:r></w:hyperlink>'
    if boundary == "same_target_different_links":
        body, start, end, expected = linked_a + linked_b, (0, 0), (1, 1), "AB"
    elif boundary == "empty_link":
        body, start, end, expected = plain_a + middle + plain_b, (0, 0), (2, 1), "AB"
    elif boundary == "end_at_zero":
        body, start, end, expected = plain_a + linked_b, (0, 0), (1, 0), "A"
    elif boundary == "start_at_length":
        body, start, end, expected = linked_a + plain_b, (0, 1), (1, 1), "B"
    else:
        body, start, end, expected = plain_a + linked_b, (0, 0), (1, 1), "AB"
    data, _, spans = source("<w:p>" + body + "</w:p>")
    candidate = make_edit(spans, start, end, expected, "new")
    reject(
        lambda: module.export_docx_ranges(data, (candidate,)),
        module.RangeError,
        "unsupported_range",
    )
    assert (
        module.export_docx_ranges(data, (make_edit(spans, start, end, expected, expected),)) == data
    )


def test_bookmark_markers_between_element_paths_block_only_actual_changes():
    module = api()
    for marker in ('<w:bookmarkStart w:id="1" w:name="bookmark"/>', '<w:bookmarkEnd w:id="1"/>'):
        data, _, spans = source(
            "<w:p><w:pPr/><w:r><w:rPr/><w:t>A</w:t></w:r><!--ignored-->"
            + marker
            + "<?keep value?><w:r><w:t>B</w:t></w:r></w:p>"
        )
        assert (spans[0].anchor.path, spans[1].anchor.path) == ((0, 0, 1, 1), (0, 0, 3, 0))
        for start, end, expected in (
            ((0, 0), (1, 1), "AB"),
            ((0, 0), (1, 0), "A"),
            ((0, 1), (1, 1), "B"),
        ):
            reject(
                lambda: module.export_docx_ranges(
                    data, (make_edit(spans, start, end, expected, "X"),)
                ),
                module.RangeError,
                "unsupported_range",
            )
        assert (
            module.export_docx_ranges(data, (make_edit(spans, (0, 0), (1, 1), "AB", "AB"),)) == data
        )


def test_bookmarks_outside_range_and_foreign_names_in_properties_do_not_block():
    module = api()
    data, _, spans = source(
        '<w:p><w:bookmarkStart w:id="1"/><w:r><w:t>A</w:t></w:r>'
        "<w:r><w:rPr><s:bookmarkEnd/></w:rPr><w:t>B</w:t></w:r>"
        '<w:bookmarkEnd w:id="1"/></w:p>'
    )
    result = module.export_docx_ranges(data, (make_edit(spans, (0, 0), (1, 1), "AB", "X"),))
    assert projection_api().project_docx(result).blocks[0].text == "X"


def test_new_controls_are_range_errors_but_retained_controls_inherit_edit_error():
    module = api()
    data, _, spans = source(paragraph("abc"))
    for control in ("\t", "\r", "\n"):
        candidate = make_edit(spans, (0, 0), (0, 1), "a", "x" + control)
        reject(
            lambda: module.export_docx_ranges(data, (candidate,)),
            module.RangeError,
            "unsupported_range",
        )
    data, _, spans = source("<w:p><w:r><w:t>a&#9;b</w:t></w:r></w:p>")
    candidate = make_edit(spans, (0, 0), (0, 1), "a", "A")
    reject(
        lambda: module.export_docx_ranges(data, (candidate,)),
        editing_api().EditError,
        "unsupported_edit",
    )
    assert module.export_docx_ranges(data, (simple_edit(spans, spans[0].text),)) == data


def test_invalid_xml_replacement_is_safe_range_input_error():
    module = api()
    data, _, spans = source()
    for char in ("\0", "\x0b", "\ud800", "\udfff", "\ufffe", "\uffff"):
        reject(
            lambda: module.export_docx_ranges(data, (simple_edit(spans, PRIVATE + char),)),
            module.RangeError,
            "invalid_input",
        )


@pytest.mark.parametrize("case", ["comment", "signature", "tracking", "protection"])
def test_lower_edit_gates_are_preserved_with_their_original_error_class(case):
    module = api()
    if case == "comment":
        data, _, spans = source("<w:p><w:r><w:t>ab<!--keep-->cd</w:t></w:r></w:p>")
    elif case == "signature":
        data, _, spans = source(extra_parts={"_xmlsignatures/sig.xml": b"<signature/>"})
    else:
        tag = "trackRevisions" if case == "tracking" else "documentProtection"
        data, _, spans = source(
            extra_parts={
                "custom/settings.xml": (
                    f'<w:settings xmlns:w="{WORD_NS}"><w:{tag}/></w:settings>'
                ).encode()
            },
            extra_types={"custom/settings.xml": SETTINGS_TYPE},
        )
    assert module.export_docx_ranges(data, (simple_edit(spans, spans[0].text),)) == data
    reject(
        lambda: module.export_docx_ranges(data, (simple_edit(spans),)),
        editing_api().EditError,
        "unsupported_edit",
    )


def test_entry_and_replacement_budgets_include_noops_and_are_inclusive():
    module = api()
    data, _, spans = source(paragraph("AB"))
    candidates = (
        make_edit(spans, (0, 0), (0, 1), "A", "A"),
        make_edit(spans, (0, 1), (0, 2), "B", "B"),
    )
    assert (
        module.export_docx_ranges(
            data,
            candidates,
            range_limits=module.RangeLimits(max_edits=2, max_total_replacement_chars=2),
        )
        == data
    )
    for limits in (
        module.RangeLimits(max_edits=1),
        module.RangeLimits(max_total_replacement_chars=1),
    ):
        reject(
            lambda: module.export_docx_ranges(data, candidates, range_limits=limits),
            module.RangeError,
            "range_limit_exceeded",
        )
    candidate = make_edit(spans, (0, 0), (0, 1), "A", "\U0001f600")
    result = module.export_docx_ranges(
        data, (candidate,), range_limits=module.RangeLimits(max_total_replacement_chars=1)
    )
    assert projection_api().project_docx(result).blocks[0].text == "\U0001f600B"


def test_touched_span_budget_counts_empty_and_end_at_zero_but_not_noops():
    module = api()
    data, _, spans = source("<w:p><w:r><w:t>A</w:t><w:t/><w:t>B</w:t></w:r></w:p>")
    candidate = make_edit(spans, (0, 0), (2, 0), "A", "X")
    reject(
        lambda: module.export_docx_ranges(
            data, (candidate,), range_limits=module.RangeLimits(max_touched_spans=2)
        ),
        module.RangeError,
        "range_limit_exceeded",
    )
    result = module.export_docx_ranges(
        data, (candidate,), range_limits=module.RangeLimits(max_touched_spans=3)
    )
    assert projection_api().project_docx(result).blocks[0].text == "XB"
    noop = make_edit(spans, (0, 0), (2, 1), "AB", "AB")
    assert (
        module.export_docx_ranges(
            data, (noop,), range_limits=module.RangeLimits(max_touched_spans=1)
        )
        == data
    )


def test_touched_span_budget_deduplicates_shared_span_across_adjacent_ranges():
    module = api()
    data, _, spans = source("<w:p><w:r><w:t>ab</w:t><w:t>cd</w:t><w:t>ef</w:t></w:r></w:p>")
    candidates = (
        make_edit(spans, (0, 1), (1, 1), "bc", "X"),
        make_edit(spans, (1, 1), (2, 1), "de", "Y"),
    )
    result = module.export_docx_ranges(
        data, candidates, range_limits=module.RangeLimits(max_touched_spans=3)
    )
    assert projection_api().project_docx(result).blocks[0].text == "aXYf"
    reject(
        lambda: module.export_docx_ranges(
            data, candidates, range_limits=module.RangeLimits(max_touched_spans=2)
        ),
        module.RangeError,
        "range_limit_exceeded",
    )


def test_empty_batch_still_checks_input_package_and_projection_limits():
    module = api()
    data, _, _ = source()
    for bad in (None, "bytes", bytearray(b"bad")):
        reject(lambda: module.export_docx_ranges(bad, ()), package_api().DocxError, "invalid_input")
    reject(
        lambda: module.export_docx_ranges(PRIVATE.encode(), ()),
        package_api().DocxError,
        "invalid_package",
    )
    reject(
        lambda: module.export_docx_ranges(data, (), limits={}),
        package_api().DocxError,
        "invalid_input",
    )
    reject(
        lambda: module.export_docx_ranges(data, (), projection_limits={}),
        projection_api().ProjectionError,
        "invalid_input",
    )
    reject(
        lambda: module.export_docx_ranges(
            data, (), projection_limits=projection_api().ProjectionLimits(max_nodes=1)
        ),
        projection_api().ProjectionError,
        "projection_limit_exceeded",
    )


def test_output_growth_preserves_lower_package_limit_error():
    module = api()
    data, _, spans = source(paragraph("AB"))
    candidate = make_edit(spans, (0, 0), (0, 1), "A", "<&" * 2000)
    limits = package_api().DocxLimits(max_xml_bytes=2000)
    assert module.export_docx_ranges(data, (), limits=limits) == data
    reject(
        lambda: module.export_docx_ranges(data, (candidate,), limits=limits),
        package_api().DocxError,
        "package_limit_exceeded",
    )


def test_invalid_later_range_returns_no_partial_result_and_source_remains_usable():
    module = api()
    data, _, spans = source(paragraph("abc") + paragraph("def"))
    before = bytes(data)
    valid = make_edit(spans, (0, 0), (0, 1), "a", "X")
    invalid = make_edit(spans, (1, 0), (1, 1), PRIVATE, "Y")
    reject(
        lambda: module.export_docx_ranges(data, (valid, invalid)),
        module.RangeError,
        "text_mismatch",
    )
    assert data == before
    assert [b.text for b in projection_api().project_docx(data).blocks] == ["abc", "def"]
    result = module.export_docx_ranges(data, (valid,))
    assert [b.text for b in projection_api().project_docx(result).blocks] == ["Xbc", "def"]


def test_imports_and_range_operations_have_no_external_io_or_logging():
    api()
    data, _, _ = source(paragraph("abc"))
    code = """
import base64, builtins, importlib, io, json, logging, os, socket, subprocess, tempfile
from pathlib import Path
import urllib.request, zipfile, dataclasses, hashlib, copy, re, struct, codecs
from xml.etree import ElementTree
import xml.parsers.expat
import psycopg, sqlalchemy
import ara.config, ara.db
import ara.docx_package.projection as projection
import ara.docx_package.editing
raw = base64.b64decode(PAYLOAD)
span = projection.project_docx(raw).blocks[0].spans[0]
names = ['ara.docx_package.ranges'] + [
    '.'.join(p.with_suffix('').parts[1:])
    for p in sorted(Path('src/ara/docx_package/ranges').rglob('*.py'))
    if p.name != '__init__.py'
]
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external I/O or logging in ranges')
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
module = importlib.import_module('ara.docx_package.ranges')
value = module.RangeEdit(module.TextPosition(span.anchor, 1),
    module.TextPosition(span.anchor, 2), 'b', 'X')
result = module.export_docx_ranges(raw, (value,))
assert projection.project_docx(result).blocks[0].text == 'aXc'
assert module.export_docx_ranges(raw, ()) == raw
try:
    bad = module.RangeEdit(module.TextPosition(span.anchor, 0),
        module.TextPosition(span.anchor, 1), 'wrong', 'X')
    module.export_docx_ranges(raw, (bad,))
except module.RangeError as error:
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
