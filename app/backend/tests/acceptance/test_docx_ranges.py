"""Independent positive acceptance for source-addressed DOCX text ranges."""

from hashlib import sha256
from importlib import import_module
from itertools import permutations
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import pytest
from docx_editing_fixtures import MAIN, projection_api, text_spans, zip_parts
from docx_projection_fixtures import REL_ATTR_NS, XML_NS, package, paragraph

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/docx/rich-source.docx"


def api():
    return import_module("ara.docx_package.ranges")


def formatted_paragraph(*texts):
    runs = []
    styles = ("<w:b/>", "<w:i/>", '<w:u w:val="single"/>')
    for index, text in enumerate(texts):
        runs.append(
            f"<w:r><w:rPr>{styles[index % len(styles)]}</w:rPr>"
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
        )
    return '<w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr>' + "".join(runs) + "</w:p>"


def change(start, start_offset, end, end_offset, expected, replacement):
    surface = api()
    return surface.RangeEdit(
        surface.TextPosition(start.anchor, start_offset),
        surface.TextPosition(end.anchor, end_offset),
        expected,
        replacement,
    )


def spans(data):
    return text_spans(projection_api().project_docx(data))


def assert_result(raw, output, expected, *, main=MAIN):
    assert type(output) is bytes
    before, after = zip_parts(raw), zip_parts(output)
    assert list(before) == list(after)
    assert {key: value for key, value in before.items() if key != main} == {
        key: value for key, value in after.items() if key != main
    }
    previous, current = spans(raw), spans(output)
    assert [span.text for span in current] == expected
    assert [span.anchor.path for span in current] == [span.anchor.path for span in previous]
    assert all(span.anchor.source_sha256 == sha256(output).hexdigest() for span in current)
    # Restore only text and the allowed xml:space change, then compare all other
    # XML properties and structure independently of the implementation.
    before_tree, after_tree = ET.fromstring(before[main]), ET.fromstring(after[main])
    for old, new in zip(previous, current, strict=True):
        before_node, after_node = before_tree, after_tree
        for index in old.anchor.path:
            before_node, after_node = before_node[index], after_node[index]
        if old.text != new.text:
            assert after_node.attrib == {**before_node.attrib, f"{{{XML_NS}}}space": "preserve"}
            after_node.text = before_node.text
            after_node.attrib.clear()
            after_node.attrib.update(before_node.attrib)
    assert ET.tostring(before_tree) == ET.tostring(after_tree)
    assert (
        import_module("ara.docx_package").export_original(projection_api().project_docx(raw).source)
        == raw
    )


def test_substring_replacement_keeps_prefix_suffix_and_run_properties():
    raw, xml = package(formatted_paragraph("the relay shall act"))
    node = spans(raw)[0]
    request = change(node, 4, node, 9, "relay", "sensor")
    output = api().export_docx_ranges(raw, (request,))
    assert_result(raw, output, ["the sensor shall act"])
    assert zip_parts(output)[MAIN] == xml.replace(
        b">the relay shall act<", b">the sensor shall act<"
    )


@pytest.mark.parametrize("offset", [0, 3, 5])
def test_insert_at_beginning_middle_or_end_of_one_span(offset):
    raw, _ = package(formatted_paragraph("abcde"))
    node = spans(raw)[0]
    request = change(node, offset, node, offset, "", "INSERT")
    output = api().export_docx_ranges(raw, (request,))
    assert_result(raw, output, ["abcde"[:offset] + "INSERT" + "abcde"[offset:]])


@pytest.mark.parametrize(("start", "end", "expected"), [(1, 4, "ae"), (0, 5, "")])
def test_delete_substring_or_all_text_keeps_the_existing_run(start, end, expected):
    raw, _ = package(formatted_paragraph("abcde"))
    node = spans(raw)[0]
    output = api().export_docx_ranges(
        raw, (change(node, start, node, end, "abcde"[start:end], ""),)
    )
    assert_result(raw, output, [expected])


def test_cross_run_replacement_uses_start_format_and_keeps_end_suffix_format():
    raw, _ = package(formatted_paragraph("left RED", "GREEN", "BLUE right"))
    nodes = spans(raw)
    request = change(nodes[0], 5, nodes[2], 4, "REDGREENBLUE", "new")
    output = api().export_docx_ranges(raw, (request,))
    assert_result(raw, output, ["left new", "", " right"])


def test_cross_run_end_zero_preserves_the_entire_end_node():
    raw, _ = package(formatted_paragraph("first", "tail"))
    first, second = spans(raw)
    output = api().export_docx_ranges(raw, (change(first, 2, second, 0, "rst", "X"),))
    assert_result(raw, output, ["fiX", "tail"])


@pytest.mark.parametrize("left_donor", [False, True])
def test_boundary_caret_anchor_explicitly_selects_format_donor(left_donor):
    raw, _ = package(formatted_paragraph("ab", "cd"))
    first, second = spans(raw)
    donor, offset = (first, 2) if left_donor else (second, 0)
    output = api().export_docx_ranges(raw, (change(donor, offset, donor, offset, "", "X"),))
    assert_result(raw, output, ["abX", "cd"] if left_donor else ["ab", "Xcd"])


def test_insertion_in_existing_empty_span_uses_that_span_and_preserves_neighbors():
    raw, _ = package(formatted_paragraph("ab", "", "cd"))
    node = spans(raw)[1]
    output = api().export_docx_ranges(raw, (change(node, 0, node, 0, "", "X"),))
    assert_result(raw, output, ["ab", "X", "cd"])


def test_empty_start_and_end_spans_are_valid_explicit_range_endpoints():
    raw, _ = package(formatted_paragraph("", "ab", "", "cd"))
    nodes = spans(raw)
    output = api().export_docx_ranges(raw, (change(nodes[0], 0, nodes[2], 0, "ab", "X"),))
    assert_result(raw, output, ["X", "", "", "cd"])


def test_cross_run_range_keeps_intermediate_empty_nodes():
    raw, _ = package(formatted_paragraph("ab", "", "", "cd"))
    nodes = spans(raw)
    output = api().export_docx_ranges(raw, (change(nodes[0], 1, nodes[3], 1, "bc", "X"),))
    assert_result(raw, output, ["aX", "", "", "d"])


def test_multiple_ranges_in_one_span_use_source_offsets_in_every_input_order():
    raw, _ = package(formatted_paragraph("0123456789"))
    node = spans(raw)[0]
    requests = (
        change(node, 1, node, 3, "12", "A"),
        change(node, 5, node, 8, "567", "B"),
        change(node, 9, node, 10, "9", "C"),
    )
    results = [api().export_docx_ranges(raw, order) for order in permutations(requests)]
    assert all(output == results[0] for output in results)
    assert_result(raw, results[0], ["0A34B8C"])


def test_adjacent_ranges_can_share_start_span_at_its_end_without_losing_inserted_text():
    raw, _ = package(formatted_paragraph("ab", "cd"))
    first, second = spans(raw)
    requests = (
        change(first, 0, first, 2, "ab", "X"),
        change(first, 2, second, 2, "cd", "Y"),
    )
    limits = api().RangeLimits(max_edits=2, max_total_replacement_chars=2, max_touched_spans=2)
    output = api().export_docx_ranges(raw, requests, range_limits=limits)
    assert output == api().export_docx_ranges(raw, tuple(reversed(requests)), range_limits=limits)
    assert_result(raw, output, ["XY", ""])


def test_adjacent_cross_run_ranges_can_touch_the_same_middle_span():
    raw, _ = package(formatted_paragraph("ab", "cd", "ef"))
    first, second, third = spans(raw)
    requests = (
        change(first, 0, second, 1, "abc", "X"),
        change(second, 1, third, 2, "def", "Y"),
    )
    output = api().export_docx_ranges(raw, requests)
    assert output == api().export_docx_ranges(raw, tuple(reversed(requests)))
    assert_result(raw, output, ["X", "Y", ""])


def test_nonconflicting_insertions_and_replacement_in_same_span_are_merged_once():
    raw, _ = package(formatted_paragraph("abcdef"))
    node = spans(raw)[0]
    requests = (
        change(node, 0, node, 0, "", "P"),
        change(node, 2, node, 4, "cd", "Q"),
        change(node, 6, node, 6, "", "Z"),
    )
    results = [api().export_docx_ranges(raw, order) for order in permutations(requests)]
    assert all(output == results[0] for output in results)
    assert_result(raw, results[0], ["PabQefZ"])


def test_unicode_offsets_are_code_points_and_combining_characters_are_not_normalized():
    raw, _ = package(formatted_paragraph("A😀e\u0301ЖZ"))
    node = spans(raw)[0]
    output = api().export_docx_ranges(raw, (change(node, 1, node, 4, "😀e\u0301", "⚙"),))
    assert_result(raw, output, ["A⚙ЖZ"])


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_range_export_preserves_nonstandard_main_and_supported_namespace_encoding(strict, encoding):
    main = "custom/Document.XML"
    raw, _ = package(
        formatted_paragraph("Реле", " и свет"), main_part=main, strict=strict, encoding=encoding
    )
    first, second = spans(raw)
    output = api().export_docx_ranges(raw, (change(first, 2, second, 3, "ле и ", "тор"),))
    assert_result(raw, output, ["Ретор", "свет"], main=main)


def test_nested_table_ranges_stay_in_their_cells_and_batches_can_change_other_cells():
    body = (
        '<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
        + paragraph("Outer")
        + "<w:tbl><w:tr><w:tc>"
        + formatted_paragraph("ab", "cd")
        + "</w:tc><w:tc>"
        + formatted_paragraph("next")
        + "</w:tc></w:tr></w:tbl><w:p/></w:tc></w:tr></w:tbl>"
    )
    raw, _ = package(body)
    _, first, second, other = spans(raw)
    requests = (change(first, 1, second, 1, "bc", "X"), change(other, 1, other, 3, "ex", "EW"))
    output = api().export_docx_ranges(raw, requests)
    assert output == api().export_docx_ranges(raw, tuple(reversed(requests)))
    assert_result(raw, output, ["Outer", "aX", "d", "nEWt"])


def test_ranges_inside_each_hyperlink_preserve_links_and_styled_run_distribution():
    body = (
        '<w:p><w:hyperlink r:id="rLink"><w:r><w:rPr><w:b/></w:rPr>'
        '<w:t xml:space="preserve">ab</w:t></w:r><w:r><w:rPr><w:i/></w:rPr>'
        '<w:t xml:space="preserve">cd</w:t></w:r></w:hyperlink>'
        '<w:hyperlink r:id="rLink"><w:r><w:t xml:space="preserve">second</w:t>'
        "</w:r></w:hyperlink></w:p>"
    )
    links = [
        {
            "Id": "rLink",
            "Type": REL_ATTR_NS + "/hyperlink",
            "Target": "https://example.invalid/never-fetch",
            "TargetMode": "External",
        }
    ]
    raw, _ = package(body, links=links)
    first, second, other_link = spans(raw)
    requests = (
        change(first, 1, second, 1, "bc", "X"),
        change(other_link, 0, other_link, 3, "sec", "TH"),
    )
    output = api().export_docx_ranges(raw, requests)
    assert_result(raw, output, ["aX", "d", "THond"])
    current = spans(output)
    assert current[0].hyperlink.anchor.path == current[1].hyperlink.anchor.path
    assert current[2].hyperlink.anchor.path != current[1].hyperlink.anchor.path
    assert all(span.hyperlink.relationship_id == "rLink" for span in current)


def test_equal_replacement_preserves_original_run_distribution_exactly():
    raw, _ = package(formatted_paragraph("ab", "cd", "ef"), comment=b"original archive")
    first, _, third = spans(raw)
    assert api().export_docx_ranges(raw, (change(first, 1, third, 1, "bcde", "bcde"),)) == raw
    assert api().export_docx_ranges(raw, ()) == raw


def test_noop_can_cross_bookmark_control_opaque_and_hyperlink_boundaries():
    body = (
        '<w:p><w:r><w:t xml:space="preserve">ab</w:t></w:r>'
        '<w:bookmarkStart w:id="1" w:name="mark"/><w:r><w:tab/><w:br/></w:r>'
        '<w:hyperlink w:anchor="mark"><w:r><w:t xml:space="preserve">cd</w:t>'
        '</w:r></w:hyperlink><w:bookmarkEnd w:id="1"/>'
        '<w:r><w:drawing><s:shape/></w:drawing><w:t xml:space="preserve">ef</w:t>'
        "</w:r></w:p>"
    )
    raw, _ = package(body)
    first, _, third = spans(raw)
    expected = "ab\t\ncd\ufffcef"
    request = change(first, 0, third, 2, expected, expected)
    assert (
        api().export_docx_ranges(
            raw, (request,), range_limits=api().RangeLimits(max_touched_spans=1)
        )
        == raw
    )


def test_markers_outside_changed_range_and_foreign_bookmark_names_are_preserved():
    body = (
        '<w:p><w:bookmarkStart w:id="1" w:name="outer"/>'
        '<w:r><w:t xml:space="preserve">ab</w:t><s:bookmarkStart/>'
        '<w:t xml:space="preserve">cd</w:t></w:r>'
        '<w:bookmarkEnd w:id="1"/></w:p>'
    )
    # Unknown foreign markup inside a run would be opaque. Put it at a root
    # location instead: foreign marker names must not become global blockers.
    body = body.replace("<s:bookmarkStart/>", "")
    raw, _ = package(body, before_body='<s:bookmarkStart s:name="foreign"/>')
    first, second = spans(raw)
    output = api().export_docx_ranges(raw, (change(first, 1, second, 1, "bc", "X"),))
    assert_result(raw, output, ["aX", "d"])


def test_one_range_over_more_than_one_thousand_spans_sets_lower_edit_budget():
    count = 1005
    raw, _ = package(formatted_paragraph(*("x" for _ in range(count))))
    nodes = spans(raw)
    request = change(nodes[0], 0, nodes[-1], 1, "x" * count, "Y")
    limits = api().RangeLimits(max_edits=1, max_total_replacement_chars=1, max_touched_spans=count)
    output = api().export_docx_ranges(raw, (request,), range_limits=limits)
    assert_result(raw, output, ["Y"] + [""] * (count - 1))


def test_short_range_in_span_larger_than_one_million_sets_lower_replacement_budget():
    original = "a" * 1000001 + "tail"
    raw, _ = package(formatted_paragraph(original))
    node = spans(raw)[0]
    request = change(node, 500000, node, 500001, "a", "B")
    limits = api().RangeLimits(max_edits=1, max_total_replacement_chars=1, max_touched_spans=1)
    output = api().export_docx_ranges(raw, (request,), range_limits=limits)
    assert_result(raw, output, [original[:500000] + "B" + original[500001:]])


def test_rich_source_cross_run_phrase_cell_and_link_substrings_preserve_all_other_content():
    raw = FIXTURE.read_bytes()
    projected = projection_api().project_docx(raw)
    phrase = projected.blocks[4].spans
    link = next(span for span in text_spans(projected) if span.hyperlink is not None)
    table = next(block for block in projected.blocks if block.kind == "table")
    cell = table.rows[1].cells[0].blocks[0].spans[0]
    requests = (
        change(
            phrase[0], 9, phrase[2], 6, "keeps a stable canonical type even ", "retains its type "
        ),
        change(link, 0, link, 9, "Synthetic", "Example"),
        change(cell, 0, cell, 1, cell.text[:1], "Q"),
    )
    expected = {span.anchor.path: span.text for span in text_spans(projected)}
    expected[phrase[0].anchor.path] = "A device retains its type "
    expected[phrase[1].anchor.path] = ""
    expected[phrase[2].anchor.path] = phrase[2].text[6:]
    expected[link.anchor.path] = "Example" + link.text[9:]
    expected[cell.anchor.path] = "Q" + cell.text[1:]
    output = api().export_docx_ranges(raw, requests)
    assert output == api().export_docx_ranges(raw, tuple(reversed(requests)))
    assert_result(raw, output, list(expected.values()))


def test_second_call_uses_new_projection_and_leaves_previous_versions_unchanged():
    raw, _ = package(formatted_paragraph("abcdef"))
    first = spans(raw)[0]
    output = api().export_docx_ranges(raw, (change(first, 1, first, 3, "bc", "XYZ"),))
    current = spans(output)[0]
    final = api().export_docx_ranges(output, (change(current, 4, current, 6, "de", "!"),))
    assert current.anchor.source_sha256 != first.anchor.source_sha256
    assert_result(raw, output, ["aXYZdef"])
    assert_result(output, final, ["aXYZ!f"])
