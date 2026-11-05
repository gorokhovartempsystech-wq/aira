import json

import pytest
from test_docx_editor_wire import view
from test_docx_visible_main import source

from ara.documents.storage import DocumentError
from ara.docx_editor.wire import encode_projection


def test_compact_preserves_text_anchors_and_structure():
    v = view()
    full = json.loads(encode_projection(v))
    compact = json.loads(encode_projection(v, compact=True))
    expected = full["projection"]["blocks"][0].copy()
    spans = expected.pop("spans")
    expected["edit_spans"] = [
        dict(kind=s["kind"], path=s["anchor"]["path"], start=s["start"], end=s["end"])
        for s in spans
    ]
    assert compact["projection"]["blocks"][0] == expected
    assert compact["view"] == full["view"]
    assert compact["projection"]["source_sha256"] == full["projection"]["source_sha256"]


def test_many_runs_fit_compact_without_raising_existing_budget():
    data = source("<w:p>" + "<w:r><w:t>x</w:t></w:r>" * 1800 + "</w:p>")[0]
    v = view(data)
    with pytest.raises(DocumentError):
        encode_projection(v)
    compact = json.loads(encode_projection(v, compact=True))
    assert compact["projection"]["blocks"][0]["text"] == "x" * 1800


def test_compact_policy_is_explicit_boolean():
    with pytest.raises(DocumentError):
        encode_projection(view(), compact=1)
