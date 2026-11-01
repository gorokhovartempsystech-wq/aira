"""Additional source-coordinate and delegation checks using synthetic DOCX bytes."""

from dataclasses import replace
from io import BytesIO
from itertools import permutations
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from ara.docx_package import DocxLimits, editing
from ara.docx_package.projection import ProjectionLimits, SourceAnchor, project_docx
from ara.docx_package.ranges import (
    RangeEdit,
    RangeError,
    RangeLimits,
    TextPosition,
    export_docx_ranges,
)

WML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def source(body):
    """Keep this fixture independent of the fixed acceptance fixture helpers."""
    parts = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/main.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.document.main+xml"/></Types>'
        ).encode(),
        "_rels/.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="main" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="main.xml"/></Relationships>'
        ).encode(),
        "main.xml": (f'<w:document xmlns:w="{WML}"><w:body>{body}</w:body></w:document>').encode(),
    }
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return stream.getvalue()


def paragraph(*texts):
    return (
        "<w:p>"
        + "".join(
            '<w:r><w:rPr><w:color w:val="%06X"/></w:rPr>'
            '<w:t xml:space="preserve">%s</w:t></w:r>' % (index, escape(text))
            for index, text in enumerate(texts)
        )
        + "</w:p>"
    )


def spans(data):
    return project_docx(data).blocks[0].spans


def change(nodes, start, end, expected, replacement):
    return RangeEdit(
        TextPosition(nodes[start[0]].anchor, start[1]),
        TextPosition(nodes[end[0]].anchor, end[1]),
        expected,
        replacement,
    )


@pytest.mark.parametrize("left_end", [(0, 2), (1, 0), (2, 0), (3, 0)])
@pytest.mark.parametrize("right_start", [(0, 2), (1, 0), (2, 0), (3, 0)])
def test_adjacent_ranges_use_absolute_conflicts_and_explicit_donors(left_end, right_start):
    raw = source(paragraph("ab", "", "", "cd"))
    nodes = spans(raw)
    requests = (
        change(nodes, (0, 0), left_end, "ab", "X"),
        change(nodes, right_start, (3, 2), "cd", "Y"),
    )
    expected = ["X", "", "", ""]
    expected[right_start[0]] += "Y"
    outputs = [export_docx_ranges(raw, order) for order in permutations(requests)]
    assert outputs[0] == outputs[1]
    assert [node.text for node in spans(outputs[0])] == expected
    assert [node.anchor.path for node in spans(outputs[0])] == [node.anchor.path for node in nodes]


def test_lower_export_receives_one_edit_per_changed_span_and_original_limits(monkeypatch):
    raw = source(paragraph("abcdef", "ghijkl", "untouched"))
    nodes = spans(raw)
    requests = (
        change(nodes, (1, 2), (1, 4), "ij", "LONG"),
        change(nodes, (0, 4), (1, 1), "efg", "Q"),
        change(nodes, (0, 1), (0, 2), "b", "BB"),
    )
    package_limits = DocxLimits()
    projection_limits = ProjectionLimits()
    actual_export = editing.export_docx
    observed = []

    def record(data, edits, **kwargs):
        observed.append((data, edits, kwargs))
        return actual_export(data, edits, **kwargs)

    monkeypatch.setattr(editing, "export_docx", record)
    output = export_docx_ranges(
        raw, requests, limits=package_limits, projection_limits=projection_limits
    )
    assert [node.text for node in spans(output)] == ["aBBcdQ", "hLONGkl", "untouched"]
    assert len(observed) == 1
    data, lower_edits, kwargs = observed[0]
    assert data is raw
    assert type(lower_edits) is tuple
    assert len(lower_edits) == 2
    assert {edit.anchor: (edit.expected_text, edit.replacement_text) for edit in lower_edits} == {
        nodes[0].anchor: ("abcdef", "aBBcdQ"),
        nodes[1].anchor: ("ghijkl", "hLONGkl"),
    }
    assert kwargs["limits"] is package_limits
    assert kwargs["projection_limits"] is projection_limits
    assert kwargs["edit_limits"] == editing.EditLimits(max_edits=2, max_total_replacement_chars=13)


@pytest.mark.parametrize("mode", ["empty", "noop", "net_unchanged"])
def test_unchanged_export_still_delegates_once_with_explicit_minimum_budgets(monkeypatch, mode):
    raw = source(paragraph("ab"))
    nodes = spans(raw)
    requests = {
        "empty": (),
        "noop": (change(nodes, (0, 0), (0, 2), "ab", "ab"),),
        "net_unchanged": (
            change(nodes, (0, 0), (0, 1), "a", "ab"),
            change(nodes, (0, 1), (0, 2), "b", ""),
        ),
    }[mode]
    actual_export = editing.export_docx
    observed = []

    def record(data, edits, **kwargs):
        observed.append((edits, kwargs))
        return actual_export(data, edits, **kwargs)

    monkeypatch.setattr(editing, "export_docx", record)
    assert export_docx_ranges(raw, requests) == raw
    assert len(observed) == 1
    lower_edits, kwargs = observed[0]
    assert lower_edits == ()
    assert kwargs["edit_limits"] == editing.EditLimits(max_edits=1, max_total_replacement_chars=1)


def test_guarded_noop_can_share_paragraph_with_disjoint_actual_change():
    raw = source(
        "<w:p><w:r><w:t>a</w:t><w:drawing/></w:r>"
        '<w:bookmarkStart w:id="1" w:name="bookmark"/>'
        '<w:hyperlink w:anchor="bookmark"><w:r><w:t>b</w:t></w:r></w:hyperlink>'
        '<w:bookmarkEnd w:id="1"/><w:r><w:t>cd</w:t></w:r></w:p>'
    )
    nodes = tuple(node for node in spans(raw) if node.kind == "text")
    requests = (
        change(nodes, (0, 0), (1, 1), "a\ufffcb", "a\ufffcb"),
        change(nodes, (2, 1), (2, 2), "d", "Z"),
    )
    result = export_docx_ranges(
        raw,
        requests,
        range_limits=RangeLimits(max_edits=2, max_total_replacement_chars=4, max_touched_spans=1),
    )
    assert [node.text for node in spans(result) if node.kind == "text"] == ["a", "b", "cZ"]
    with ZipFile(BytesIO(raw)) as before, ZipFile(BytesIO(result)) as after:
        assert after.read("main.xml") == before.read("main.xml").replace(
            b"<w:t>cd</w:t>", b'<w:t xml:space="preserve">cZ</w:t>'
        )


@pytest.mark.parametrize("marker", ["bookmarkStart", "bookmarkEnd"])
def test_hidden_bookmark_inside_run_uses_element_paths_ignoring_comments_and_pi(marker):
    raw = source(
        "<w:p><w:r><w:t>ab</w:t><!-- ordinary comment --><?ordinary pi?>"
        f'<w:{marker} w:id="1"/><w:t>cd</w:t></w:r></w:p>'
    )
    nodes = spans(raw)
    assert nodes[0].anchor.path[-1] == 0
    assert nodes[1].anchor.path[-1] == 2
    request = change(nodes, (0, 1), (1, 1), "bc", "X")
    with pytest.raises(RangeError) as caught:
        export_docx_ranges(raw, (request,))
    assert caught.value.code == "unsupported_range"
    assert export_docx_ranges(raw, (replace(request, replacement_text="bc"),)) == raw


@pytest.mark.parametrize("fault", ["mismatch", "conflict"])
def test_batch_validation_precedes_actual_boundary_guards_and_lower_export(monkeypatch, fault):
    raw = source("<w:p><w:r><w:t>ab</w:t><w:drawing/><w:t>cd</w:t><w:t>ef</w:t></w:r></w:p>")
    nodes = tuple(node for node in spans(raw) if node.kind == "text")
    guarded = change(nodes, (0, 1), (1, 1), "b\ufffcc", "X")
    other = (
        change(nodes, (2, 0), (2, 2), "wrong", "Q")
        if fault == "mismatch"
        else change(nodes, (1, 0), (1, 2), "cd", "Q")
    )

    def unexpected_export(*args, **kwargs):
        pytest.fail("Invalid batches must never invoke the lower exporter")

    monkeypatch.setattr(editing, "export_docx", unexpected_export)
    for requests in permutations((guarded, other)):
        with pytest.raises(RangeError) as caught:
            export_docx_ranges(raw, requests)
        assert caught.value.code == (
            "text_mismatch" if fault == "mismatch" else "conflicting_edits"
        )


@pytest.mark.parametrize("kind", ["tuple", "range", "position", "anchor", "string", "offset"])
def test_subclasses_cannot_supply_valid_looking_input_records(kind):
    raw = source(paragraph("ab"))
    nodes = spans(raw)
    request = change(nodes, (0, 0), (0, 1), "a", "X")
    requests = (request,)
    if kind == "tuple":
        requests = type("TupleSubclass", (tuple,), {})(requests)
    elif kind == "range":
        subclass = type("RangeSubclass", (RangeEdit,), {})
        subclass_request = object.__new__(subclass)
        for field in ("start", "end", "expected_text", "replacement_text"):
            object.__setattr__(subclass_request, field, getattr(request, field))
        requests = (subclass_request,)
    elif kind == "position":
        subclass = type("PositionSubclass", (TextPosition,), {})
        position = object.__new__(subclass)
        object.__setattr__(position, "anchor", nodes[0].anchor)
        object.__setattr__(position, "offset", 0)
        object.__setattr__(request, "start", position)
    elif kind == "anchor":
        subclass = type("AnchorSubclass", (SourceAnchor,), {})
        anchor = nodes[0].anchor
        object.__setattr__(
            request.start, "anchor", subclass(anchor.source_sha256, anchor.part_name, anchor.path)
        )
    elif kind == "string":
        object.__setattr__(request, "replacement_text", type("StringSubclass", (str,), {})("X"))
    else:
        object.__setattr__(request.start, "offset", type("IntSubclass", (int,), {})(0))
    with pytest.raises(RangeError) as caught:
        export_docx_ranges(raw, requests)
    assert caught.value.code == "invalid_input"
