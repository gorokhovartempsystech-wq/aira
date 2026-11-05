"""E4A conservative matching over fully revalidated synthetic review records."""

import importlib
import json
from dataclasses import replace
from hashlib import sha256
from uuid import UUID, uuid4
from xml.sax.saxutils import escape

import pytest
from test_docx_analysis_storage_codec import command, execution
from test_docx_review_v1 import canonical, issue, reply
from test_docx_visible_main import GAP, source, style

from ara.docx_analysis.presentation import finding_keys
from ara.docx_analysis.storage_codec import capture_result, capture_source, prepare_attempt
from ara.docx_analysis.visible_main import build_visible_snapshot

TEXTS = ("Distant introduction", "Left context", "abcd evidence 😀", "Right context", "Distant end")


def api():
    return importlib.import_module("ara.docx_analysis.remapping")


def paragraph(value, properties=""):
    ppr = f"<w:pPr>{properties}</w:pPr>" if properties else ""
    return f"<w:p>{ppr}<w:r><w:t>{escape(value)}</w:t></w:r></w:p>"


def records(
    texts=TEXTS,
    *,
    at=2,
    related=None,
    xml=None,
    styles=None,
    document_id=UUID(int=1),
    revision=7,
    spec=None,
    alter=None,
    comment=b"",
):
    raw = source(
        "".join(paragraph(t) for t in texts) if xml is None else xml, styles, comment=comment
    )[0]
    snapshot = build_visible_snapshot(
        raw,
        document_id=document_id,
        storage_revision=revision,
        source_sha256=sha256(raw).hexdigest(),
    )
    spec = execution() if spec is None else spec
    src = capture_source(raw, snapshot, command=command(snapshot), execution=spec)
    attempt = prepare_attempt(src, attempt_id=uuid4())
    f = snapshot.fragments[at]
    finding = issue(
        snapshot,
        fragment_id=f.fragment_id,
        span=dict(start=0, end=2, quote=f.text[:2]),
        suggestion=None,
    )
    if related is not None:
        r = snapshot.fragments[related]
        finding.update(
            type="duplicate", related=dict(fragment_id=r.fragment_id, quote=r.text, status="active")
        )
    body = reply(
        snapshot,
        [finding],
        engine=spec.engine_version,
        models=spec.models_version,
        checked=dict(
            fragments=len(snapshot.fragments), active=len(snapshot.fragments), skipped_status=0
        ),
    )
    if alter:
        alter(body, snapshot)
    result = capture_result(src, attempt, reply=canonical(body))
    return src, attempt, result


def matched(old, new):
    result = api().match_findings(old, new)
    old_key, new_key = finding_keys(*old)[0], finding_keys(*new)[0]
    assert len(result) == 1
    item = result[0]
    assert (
        item.previous_finding_id,
        item.previous_key,
        item.current_finding_id,
        item.current_key,
    ) == (old_key.finding_id, old_key.key, new_key.finding_id, new_key.key)
    assert "evidence" not in repr(result) and "Synthetic" not in repr(result)
    assert api().match_findings(old, new) == result
    return result


def test_exact_bytes_different_revision_and_attempt_keep_exact_key():
    old, new = records(), records(revision=8)
    item = matched(old, new)[0]
    assert (
        item.previous_key == item.current_key
        and item.previous_finding_id != item.current_finding_id
    )


def test_archive_metadata_change_does_not_break_valid_cross_source_match():
    old, new = records(), records(comment=b"different ZIP metadata")
    assert old[0].source_sha256 != new[0].source_sha256
    assert matched(old, new)[0].previous_key != finding_keys(*new)[0].key


@pytest.mark.parametrize("kind", ["insert", "delete", "edit"])
def test_far_edit_preserves_unique_evidence_and_neighbor_context(kind):
    old = records()
    if kind == "insert":
        new = records(("New distant",) + TEXTS, at=3)
    elif kind == "delete":
        new = records(TEXTS[:-1])
    else:
        new = records(("Changed far intro",) + TEXTS[1:])
    matched(old, new)


@pytest.mark.parametrize("kind", ["insert", "delete", "edit", "evidence", "split", "join"])
def test_adjacent_or_evidence_structure_changes_never_inherit(kind):
    old = records()
    values = list(TEXTS)
    at = 2
    if kind == "insert":
        values.insert(2, "New immediate neighbor")
        at = 3
    elif kind == "delete":
        del values[1]
        at = 1
    elif kind == "edit":
        values[1] = "Changed left context"
    elif kind == "evidence":
        values[2] += " changed after quote"
    elif kind == "split":
        values[2:3] = ["abcd", " evidence 😀"]
    else:
        values[2:4] = [values[2] + values[3]]
    assert api().match_findings(old, records(values, at=at)) == ()


@pytest.mark.parametrize("side", ["previous", "current"])
def test_duplicate_full_paragraph_is_not_resolved_by_nearest_quote(side):
    regular = records()
    duplicated = records(TEXTS + (TEXTS[2],))
    pair = (duplicated, regular) if side == "previous" else (regular, duplicated)
    assert api().match_findings(*pair) == ()


def test_repeated_short_quotes_in_distinct_full_paragraphs_are_not_confused():
    values = TEXTS + ("ab another requirement", "Tail")
    old, new = records(values), records(("Prefix",) + values, at=3)
    matched(old, new)


def test_intact_group_moved_across_unchanged_paragraphs_is_not_transferred():
    left = ("L0", "L1", "L2")
    group = ("Before", "abcd evidence", "After")
    right = ("R0", "R1", "R2")
    old = records(left + group + right, at=4)
    new = records(left + right + group, at=7)
    assert api().match_findings(old, new) == ()


def test_changed_distant_heading_blocks_matching_after_it():
    def body(heading):
        return paragraph(heading, '<w:outlineLvl w:val="0"/>') + "".join(
            paragraph(t) for t in TEXTS
        )

    old, new = records(xml=body("Heading A"), at=3), records(xml=body("Heading B"), at=3)
    assert api().match_findings(old, new) == ()


@pytest.mark.parametrize("kind", ["paragraph", "style", "section"])
def test_formatting_style_or_section_context_changes_are_conservative(kind):
    body = "".join(paragraph(t) for t in TEXTS)
    if kind == "paragraph":
        changed = "".join(
            paragraph(t, '<w:jc w:val="center"/>' if i == 2 else "") for i, t in enumerate(TEXTS)
        )
        old, new = records(xml=body), records(xml=changed)
    elif kind == "style":
        old = records(styles=style("Body", "<w:rPr><w:b/></w:rPr>"))
        new = records(styles=style("Body", "<w:rPr><w:i/></w:rPr>"))
    else:
        old = records(xml=body + '<w:sectPr><w:pgSz w:w="11906"/></w:sectPr>')
        new = records(xml=body + '<w:sectPr><w:pgSz w:w="12240"/></w:sectPr>')
    assert api().match_findings(old, new) == ()


def test_hidden_gap_and_unicode_slices_map_only_when_whole_paragraph_is_unchanged():
    body = paragraph("Far") + paragraph("Before") + GAP + paragraph("After") + paragraph("Tail")

    def gap_span(body, snapshot):
        body["issues"][0]["span"] = dict(start=1, end=3, quote="bc")

    old = records(xml=body, alter=gap_span)
    new = records(xml=paragraph("Prefix") + body, at=3, alter=gap_span)
    matched(old, new)
    hidden_changed = records(xml=body.replace("SECRET", "OTHER"), alter=gap_span)
    assert api().match_findings(old, hidden_changed) == ()
    texts = TEXTS[:2] + ("😀é абзац",) + TEXTS[3:]
    matched(records(texts), records(("New",) + texts, at=3))


@pytest.mark.parametrize("change", [False, True])
def test_related_evidence_also_needs_unique_unchanged_context(change):
    values = TEXTS + ("Before related", "Related requirement", "After related", "End")
    old = records(values, related=6)
    changed = list(values)
    if change:
        changed[6] += " changed"
    new = records(("Prefix",) + tuple(changed), at=3, related=7)
    if change:
        assert api().match_findings(old, new) == ()
    else:
        matched(old, new)


@pytest.mark.parametrize(
    "field,value",
    [
        ("severity", "critical"),
        ("light", "red"),
        ("explanation", "Changed"),
        ("rule", "Different rule"),
        ("question", "Different?"),
    ],
)
def test_changed_issue_meaning_never_inherits(field, value):
    def alter(body, snapshot):
        body["issues"][0][field] = value
        body["questions"] = [body["issues"][0]["question"]]

    assert api().match_findings(records(), records(("Prefix",) + TEXTS, at=3, alter=alter)) == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_kind", "local_model"),
        ("models_version", "synthetic-2"),
        ("model_sha256", "3" * 64),
        ("adapter_sha256", "4" * 64),
    ],
)
def test_execution_identity_change_never_inherits(field, value):
    assert api().match_findings(records(), records(spec=execution(**{field: value}))) == ()


def test_private_upstream_noise_does_not_change_match():
    def alter(body, snapshot):
        body["issues"][0].update(
            id="iss-aaaaaaaaaa",
            confidence=0.1,
            suggestion=dict(before=snapshot.fragments[3].text[:2], after="Other"),
        )

    matched(records(), records(("Prefix",) + TEXTS, at=3, alter=alter))


@pytest.mark.parametrize(
    "index,field",
    [
        (0, "source_data"),
        (0, "snapshot_data"),
        (1, "request_data"),
        (2, "reply_data"),
        (2, "result_data"),
    ],
)
def test_corrupt_storage_never_returns_partial_mapping(index, field):
    good = records()
    broken = list(good)
    broken[index] = replace(broken[index], **{field: b"SYNTHETIC_PRIVATE"})
    with pytest.raises(api().RemapError) as caught:
        api().match_findings(good, tuple(broken))
    assert caught.value.code == "corrupt_result" and "SYNTHETIC_PRIVATE" not in str(caught.value)


def test_cross_document_and_invalid_arguments_fail_without_mutation():
    old = records()
    original = tuple(repr(x) for x in old)
    with pytest.raises(api().RemapError) as caught:
        api().match_findings(old, records(document_id=uuid4()))
    assert caught.value.code == "invalid_input"
    for wrong in (None, [], old[:2]):
        with pytest.raises(api().RemapError) as caught:
            api().match_findings(wrong, old)
        assert caught.value.code == "invalid_input"
    assert tuple(repr(x) for x in old) == original


def test_explicit_lower_budget_rejects_whole_mapping():
    old, new = records(), records(comment=b"new")
    with pytest.raises(api().RemapError) as caught:
        api().match_findings(old, new, limits=api().RemapLimits(max_paragraphs=2))
    assert caught.value.code == "limit_exceeded"
    for maximum in (True, 0, 10001):
        with pytest.raises(api().RemapError) as caught:
            api().RemapLimits(max_paragraphs=maximum)
        assert caught.value.code == "invalid_input"
    assert json.loads(old[2].result_data)["findings"][0]["primary"]["quote"] == "ab"


def test_hash_correct_forged_result_is_revalidated():
    old = records()
    body = json.loads(old[2].result_data)
    body["findings"][0]["explanation"] = "Forged semantic result"
    raw = canonical(body)
    broken = old[:2] + (replace(old[2], result_data=raw, result_sha256=sha256(raw).hexdigest()),)
    with pytest.raises(api().RemapError) as caught:
        api().match_findings(old, broken)
    assert caught.value.code == "corrupt_result"


def test_boundary_and_empty_neighbor_changes_do_not_look_like_far_edits():
    old = records(TEXTS, at=0)
    new = records(("Prefix",) + TEXTS, at=1)
    assert api().match_findings(old, new) == ()
    xml = "".join(paragraph(t) for t in TEXTS)
    gap = (
        "".join(paragraph(t) for t in TEXTS[:2])
        + "<w:p/>"
        + "".join(paragraph(t) for t in TEXTS[2:])
    )
    assert api().match_findings(records(xml=xml), records(xml=gap)) == ()


def test_multiple_issues_match_deterministically_and_findings_budget_is_total():
    def two(body, snapshot):
        first = body["issues"][0]
        body["issues"].append(dict(first, id="iss-aaaaaaaaaa", explanation="Another explanation"))

    old, new = records(alter=two), records(("Prefix",) + TEXTS, at=3, alter=two)
    result = api().match_findings(old, new)
    assert len(result) == 2
    assert [r.previous_finding_id for r in result] == sorted(r.previous_finding_id for r in result)
    assert {r.previous_key for r in result} == {k.key for k in finding_keys(*old)}
    assert {r.current_key for r in result} == {k.key for k in finding_keys(*new)}
    with pytest.raises(api().RemapError) as caught:
        api().match_findings(old, new, limits=api().RemapLimits(max_findings=1))
    assert caught.value.code == "limit_exceeded"


def test_order_inversion_rejects_both_groups_instead_of_choosing_a_longest_subsequence():
    left, group, right = (
        ("L0", "L1", "L2"),
        ("Before", "abcd evidence", "After"),
        ("R0", "R1", "R2"),
    )
    old = records(left + group + right, at=7)
    new = records(left + right + group, at=4)
    assert api().match_findings(old, new) == ()


def test_whitespace_only_neighbor_is_not_normalized_to_an_identical_empty_paragraph():
    prefix = "".join(paragraph(t) for t in TEXTS[:2])
    suffix = "".join(paragraph(t) for t in TEXTS[2:])
    old = records(xml=prefix + paragraph(" ") + suffix)
    new = records(xml=prefix + paragraph("  ") + suffix)
    assert api().match_findings(old, new) == ()


def test_matching_needs_no_files_network_database_or_secrets(monkeypatch):
    import builtins
    import socket

    import sqlalchemy

    module = api()
    old, new = records(), records(("Prefix",) + TEXTS, at=3)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected external I/O")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(sqlalchemy, "create_engine", forbidden)
        result = module.match_findings(old, new)
    assert len(result) == 1
