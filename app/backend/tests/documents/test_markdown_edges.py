"""Structural edge cases beyond the supported acceptance example."""

import pytest

from ara.documents.markdown import split_markdown


@pytest.mark.parametrize("fence", ["````", "~~~~"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_only_a_matching_long_enough_fence_closes_code(fence, newline):
    other = "~~~~" if fence[0] == "`" else "````"
    code = newline.join([fence, "# Inside", fence[:3], other, "", fence + fence[0]])
    source = code + newline + "# Outside"
    blocks = split_markdown(source)
    assert [block["kind"] for block in blocks] == ["code", "heading"]
    assert blocks[0]["text"] == code + newline
    assert "".join(block["text"] for block in blocks) == source


def test_unclosed_fence_reports_unsupported_without_losing_tail():
    source = "# Header\n~~~python\n# Still inside\n\nprint('synthetic')"
    blocks = split_markdown(source)
    assert [block["kind"] for block in blocks] == ["heading", "unsupported"]
    assert "".join(block["text"] for block in blocks) == source


def test_adjacent_structures_and_list_continuations_remain_separate():
    source = (
        "## Header\n1. First\n   continued\n2. Second\n"
        "Name | Type\n:--- | ---:\nLight | Relay\n```text\nbody | code\n```"
    )
    blocks = split_markdown(source)
    assert [block["kind"] for block in blocks] == ["heading", "list", "table", "code"]
    assert "continued" in blocks[1]["text"]
    assert "".join(block["text"] for block in blocks) == source
