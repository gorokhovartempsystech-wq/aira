"""Lossless boundaries needed by the backend/ML document contract."""

import pytest


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_structured_markdown_keeps_tables_and_code_separate(newline, fence):
    table = "| Device | Type |\n| --- | --- |\n| Switch | Relay |".replace("\n", newline)
    code = f'{fence}json\n{{"device_type": "relay"}}\n\n# Not a heading\n{fence}'.replace(
        "\n", newline
    )
    source = newline.join(
        [
            "# Device requirements",
            "",
            "Exact  text: ё 🚀.",
            "",
            "- One",
            "- Two",
            "",
            table,
            "",
            code,
            "",
            "Final paragraph without newline",
        ]
    )
    from ara.documents.markdown import split_markdown

    blocks = split_markdown(source)
    assert blocks
    assert "".join(block["text"] for block in blocks) == source
    assert {block["kind"] for block in blocks} >= {"heading", "paragraph", "list", "table", "code"}
    assert all(set(block) == {"id", "kind", "text"} for block in blocks)
    assert all(isinstance(block["id"], str) and block["id"].strip() for block in blocks)
    assert len({block["id"] for block in blocks}) == len(blocks)
    tables = [block for block in blocks if block["kind"] == "table"]
    codes = [block for block in blocks if block["kind"] == "code"]
    assert len(tables) == len(codes) == 1
    assert tables[0]["text"].strip() == table
    assert codes[0]["text"].strip() == code


@pytest.mark.parametrize(
    "source",
    [
        "  leading and trailing  ",
        "\n\n# Heading\n\nParagraph\n\n",
        "```python\nprint('synthetic')\n\n",  # Unclosed fence must never discard text.
        "<script>alert('synthetic')</script>\n",
        "| x | y |\n| no separator | ordinary text |",
        "~~~text\n```\n\n~~~\n",
        "## H\r\n\r\nText\nMixed line endings\r\n",
    ],
)
def test_edge_fragments_are_lossless(source):
    from ara.documents.markdown import split_markdown

    blocks = split_markdown(source)
    assert "".join(block["text"] for block in blocks) == source
    assert all(
        block["kind"] in {"heading", "paragraph", "list", "table", "code", "unsupported"}
        for block in blocks
    )
