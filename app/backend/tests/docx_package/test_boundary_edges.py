"""Additional D03-14 namespace growth, empty nodes and validation boundaries."""

from xml.etree import ElementTree as ET

import pytest

from ara.docx_package import DocxError, DocxLimits
from ara.docx_package.boundaries import (
    BoundaryError,
    JoinParagraphs,
    SplitParagraph,
    export_boundary,
)
from ara.docx_package.projection import (
    ProjectionError,
    ProjectionLimits,
    SourceAnchor,
    project_docx,
)
from tests.acceptance.test_docx_boundaries import W, join, p, parts, source, split, texts


def test_namespace_amplification_stops_at_output_budget():
    context = ' xmlns:q="urn:' + "a" * 6000 + '"'
    data = source(p("A") + f"<w:p{context}>" + "<w:r><w:t>B</w:t></w:r>" * 20 + "</w:p>")
    cap = len(parts(data)["word/document.xml"]) + 100
    with pytest.raises(DocxError) as caught:
        export_boundary(data, join(data), limits=DocxLimits(max_xml_bytes=cap))
    assert caught.value.code == "package_limit_exceeded"


def test_local_run_binding_shadows_rehomed_paragraph_binding():
    data = source(
        p("Left") + f'<w:p xmlns:q="urn:unused"><w:r xmlns:q="{W}">'
        "<q:rPr><q:b/></q:rPr><q:t>Right</q:t></w:r></w:p>"
    )
    result = export_boundary(data, join(data))
    assert texts(result) == ["LeftRight"]
    assert len(ET.fromstring(parts(result)["word/document.xml"]).findall(f".//{{{W}}}b")) == 1


def test_equivalent_prefixes_and_attribute_order_in_properties():
    data = source(
        p("Left", '<w:spacing w:after="20" w:before="30"/>')
        + f'<q:p xmlns:q="{W}"><q:pPr><q:spacing q:before="30" q:after="20"/>'
        "</q:pPr><q:r><q:t>Right</q:t></q:r></q:p>"
    )
    assert texts(export_boundary(data, join(data))) == ["LeftRight"]


def test_zero_width_runs_go_right_at_cut_and_are_not_duplicated():
    data = source(
        '<w:p><w:r><w:t>A</w:t></w:r><w:r w:rsidR="12345678"/>'
        "<w:r><w:t/></w:r><w:r><w:t>B</w:t></w:r></w:p>"
    )
    result = export_boundary(data, split(data, 1))
    root = ET.fromstring(parts(result)["word/document.xml"])
    a, b = root.find(f"{{{W}}}body")
    assert len(a) == 1 and len(b) == 3
    assert parts(result)["word/document.xml"].count(b"12345678") == 1


def test_output_projection_budget_rejects_growth():
    data = source(p("AB"))
    with pytest.raises(ProjectionError) as caught:
        export_boundary(data, split(data, 1), projection_limits=ProjectionLimits(max_nodes=5))
    assert caught.value.code == "projection_limit_exceeded"


def test_unknown_list_and_body_opaque_have_stable_errors():
    data = source(p("List", '<w:numPr><w:numId w:val="999"/></w:numPr>'))
    with pytest.raises(BoundaryError) as caught:
        export_boundary(data, split(data, 0))
    assert caught.value.code == "unsupported_boundary"
    data = source(
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText>'
        '<w:t>1</w:t><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    view = project_docx(data)
    anchor = SourceAnchor(view.source.sha256, view.source.main_part, (0, 0))
    with pytest.raises(BoundaryError) as caught:
        export_boundary(data, SplitParagraph(anchor, "1", 0))
    assert caught.value.code == "invalid_anchor"


def test_join_text_validation_and_missing_versus_empty_properties():
    data = source("<w:p><w:pPr/></w:p>" + p("Right"))
    assert texts(export_boundary(data, join(data))) == ["Right"]
    a, b = project_docx(data).blocks
    with pytest.raises(BoundaryError) as caught:
        export_boundary(data, JoinParagraphs(a.anchor, b.anchor, "", "wrong"))
    assert caught.value.code == "text_mismatch"
