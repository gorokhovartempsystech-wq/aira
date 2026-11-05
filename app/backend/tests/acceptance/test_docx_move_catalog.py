"""Independent structural move facts, never a final-text or coverage oracle."""

import json
from dataclasses import FrozenInstanceError, asdict, fields
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from docx_projection_fixtures import package

PRIVATE = "SYNTHETIC_PRIVATE_MOVE"


def api():
    return import_module("ara.docx_analysis.moves")


def run(text="Moved 🧪"):
    return f"<w:r><w:t>{text}</w:t></w:r>"


def group(kind="From", identity="0", name=PRIVATE, revision="91", content=None):
    return (
        f'<w:move{kind}RangeStart w:id="{identity}" w:name="{name}"/>'
        f'<w:move{kind} w:id="{revision}">{run() if content is None else content}</w:move{kind}>'
        f'<w:move{kind}RangeEnd w:id="{identity}"/>'
    )


def source(body=None, **kwargs):
    body = "<w:p>" + group() + group("To", revision="12") + "</w:p>" if body is None else body
    return package(body, main_part="custom/Moves.xml", **kwargs)


def read(raw, **kwargs):
    return api().read_move_catalog(raw, source_sha256=sha256(raw).hexdigest(), **kwargs)


def resolve(root, anchor):
    for index in anchor.path:
        root = root[index]
    return root


def check_digest(catalog):
    data = asdict(catalog)
    data.pop("catalog_sha256")
    assert (
        catalog.catalog_sha256
        == sha256(
            json.dumps(
                data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
    )


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_pinned_pair_names_and_original_xml_addresses(strict, encoding):
    # Range IDs may match across kinds; revision IDs must NOT be used as pair IDs.
    body = "<w:p>" + group("To", "0", "Перенос🧪", "12", run("New content")) + "</w:p>"
    body += (
        "<w:p>"
        + run("Unchanged")
        + group("From", "+00", "Перенос🧪", "91", run("Old content"))
        + "</w:p>"
    )
    raw, xml = source(body, strict=strict, encoding=encoding)
    before = raw
    c = read(raw)
    assert c == read(raw) and c.status == "indexed" and c.issues == ()
    assert c.profile == "docx-moves/main-inline-catalog-v1" and c.main_part == "custom/Moves.xml"
    assert not hasattr(c, "complete")
    (pair,) = c.pairs
    assert pair.name == "Перенос🧪"
    assert (pair.source.kind, pair.destination.kind) == ("from", "to")
    assert pair.source.range_id == pair.destination.range_id == 0
    assert pair.source.members[0].revision_id == 91
    assert pair.destination.members[0].revision_id == 12
    root = ET.fromstring(xml)
    for r in (pair.source, pair.destination):
        prefix = "moveFrom" if r.kind == "from" else "moveTo"
        for anchor, name in (
            (r.start, prefix + "RangeStart"),
            (r.end, prefix + "RangeEnd"),
            (r.paragraph_anchor, "p"),
        ):
            assert anchor.source_sha256 == sha256(raw).hexdigest()
            assert anchor.part_name == c.main_part
            assert resolve(root, anchor).tag.rsplit("}", 1)[-1] == name
        (member,) = r.members
        assert member.kind == r.kind and member.paragraph_anchor == r.paragraph_anchor
        assert resolve(root, member.anchor).tag.rsplit("}", 1)[-1] == prefix
    assert pair.destination.start.path == (0, 0, 0)
    assert pair.source.start.path == (0, 1, 1)
    assert pair.destination.members[0].anchor.path == (0, 0, 1)
    assert pair.source.members[0].anchor.path == (0, 1, 2)
    check_digest(c)
    assert raw == before and "Перенос" not in repr(c) + repr(pair)


def test_ordinary_content_is_not_a_member_and_pair_order_is_document_order():
    body = '<w:p><w:moveToRangeStart w:id="4" w:name="Z"/>'
    body += '<w:moveTo w:id="4">' + run("destination1") + "</w:moveTo>"
    body += run("ordinary")
    body += '<w:moveTo w:id="8">' + run("destination2") + '</w:moveTo><w:moveToRangeEnd w:id="4"/>'
    body += group("From", "6", "A") + group("To", "6", "A") + group("From", "4", "Z") + "</w:p>"
    raw, xml = source(body)
    c = read(raw)
    assert c.status == "indexed" and [p.name for p in c.pairs] == ["Z", "A"]
    destination = c.pairs[0].destination
    assert [m.anchor.path for m in destination.members] == [(0, 0, 1), (0, 0, 3)]
    assert [m.revision_id for m in destination.members] == [4, 8]
    assert all(
        "ordinary" not in "".join(resolve(ET.fromstring(xml), m.anchor).itertext())
        for m in destination.members
    )


@pytest.mark.parametrize("body", ["<w:p/>", "<w:p>" + run() + "</w:p>", "<w:p><s:opaque/></w:p>"])
def test_absence_is_main_move_absence_not_whole_document_coverage(body):
    c = read(source(body)[0])
    assert c.status == "absent" and c.pairs == c.issues == ()
    assert not hasattr(c, "complete")
    check_digest(c)


@pytest.mark.parametrize(
    "body",
    [
        '<w:p><w:moveFrom w:id="1">' + run() + "</w:moveFrom></w:p>",
        '<w:p><w:moveToRangeEnd w:id="0"/></w:p>',
        "<w:p>" + group() + "</w:p>",
        "<w:p>" + group() + group("To", name="Another") + "</w:p>",
        "<w:p>" + group() + group("From", "1") + group("To") + "</w:p>",
        "<w:p>" + group() + group("From", "-0", name="Another") + group("To") + "</w:p>",
        '<w:p><w:moveFromRangeStart w:id="0" w:name="a"/>'
        '<w:moveFromRangeStart w:id="1" w:name="b"/></w:p>',
        '<w:p><w:moveFromRangeStart w:id="0" w:name="a"/><w:moveTo w:id="1">'
        + run()
        + '</w:moveTo><w:moveFromRangeEnd w:id="0"/></w:p>',
        '<w:p><w:moveFromRangeStart w:id="0" w:name="a"/>'
        + run()
        + '<w:moveFromRangeEnd w:id="0"/></w:p>',
        '<w:p><w:moveFromRangeStart w:id="0" w:name="a"/></w:p>'
        '<w:p><w:moveFromRangeEnd w:id="0"/></w:p>',
        '<w:p><w:pPr><w:rPr><w:moveFrom w:id="1"/></w:rPr></w:pPr>'
        + group()
        + group("To")
        + "</w:p>",
        '<w:p><w:ins w:id="3">' + group() + "</w:ins>" + group("To") + "</w:p>",
        '<w:p><w:pPr><w:pPrChange w:id="7"><w:pPr><w:rPr>'
        '<w:moveTo w:id="3"/></w:rPr></w:pPr></w:pPrChange></w:pPr></w:p>',
        "<w:tbl><w:tr><w:tc><w:p>" + group() + group("To") + "</w:p></w:tc></w:tr></w:tbl>",
        "<w:p><s:opaque>" + group() + "</s:opaque>" + group("To") + "</w:p>",
    ],
)
def test_unsupported_or_unpaired_structure_never_returns_partial_pairs(body):
    raw, xml = source(body)
    c = read(raw)
    assert c.status == "blocked" and c.pairs == () and len(c.issues) == 1
    issue = c.issues[0]
    assert issue.code in {
        "unsupported_move_context",
        "invalid_move_markup",
        "duplicate_range_id",
        "duplicate_move_name",
        "nested_or_crossed_range",
        "unmatched_range",
        "unmatched_move_content",
        "empty_move_range",
        "unmatched_move",
    }
    assert resolve(ET.fromstring(xml), issue.anchor) is not None
    assert PRIVATE not in repr(c) + repr(issue)
    check_digest(c)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.replace('w:name="' + PRIVATE + '"', 'w:name=""', 1),
        lambda s: s.replace(
            'w:name="' + PRIVATE + '"', 'w:name="' + PRIVATE + '" w:colFirst="0"', 1
        ),
        lambda s: s.replace('w:id="0"', 'w:id="not-a-number"', 1),
        lambda s: s.replace('w:id="0"', 'w:id="' + "1" * 21 + '"', 1),
        lambda s: s.replace("/>", ">bad</w:moveFromRangeStart>", 1),
        lambda s: s.replace("w:moveFromRangeStart", "s:moveFromRangeStart", 1),
    ],
)
def test_invalid_marker_markup_and_foreign_range_start_fail_closed(mutation):
    raw, _ = source("<w:p>" + mutation(group()) + group("To") + "</w:p>")
    assert read(raw).status == "blocked"


def test_frozen_values_and_existing_reader_remains_closed():
    from test_docx_visible_main import build

    raw, _ = source()
    c = read(raw)
    assert c.status == "indexed" and not build(raw).complete
    for value in (c, c.pairs[0], c.pairs[0].source, c.pairs[0].source.members[0]):
        with pytest.raises(FrozenInstanceError):
            setattr(value, fields(value)[0].name, None)
    assert PRIVATE not in repr(c) + repr(c.pairs[0].source) + repr(c.pairs[0].source.members[0])
