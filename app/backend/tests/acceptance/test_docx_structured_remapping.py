"""Dismissals transfer only across source-proven structured context."""

import json
from hashlib import sha256
from uuid import UUID
from xml.sax.saxutils import escape

import pytest
from test_docx_analysis_storage_codec import command, execution
from test_docx_review_v1 import canonical, issue, reply
from test_docx_table_catalog import cell, row, table
from test_docx_visible_controls import control
from test_docx_visible_lists import paragraph as numbered
from test_docx_visible_unlisted import DEFS, selected, source

from ara.docx_analysis.presentation import finding_keys, present
from ara.docx_analysis.remapping import match_findings
from ara.docx_analysis.storage_codec import capture_result, capture_source, prepare_attempt
from ara.docx_analysis.visible_lists import build_list_snapshot

EVIDENCE = "abcd evidence 😀"


def p(text):
    return "<w:p><w:r><w:t>" + escape(text) + "</w:t></w:r></w:p>"


def body(center=None, *, intro="Distant intro", ending="Distant end"):
    return (
        p(intro)
        + p("Left context")
        + (numbered(EVIDENCE) if center is None else center)
        + p("Right context")
        + p(ending)
    )


def records(
    raw,
    *,
    target=EVIDENCE,
    related=None,
    revision=7,
    attempt=1,
    spec=None,
    document_id=UUID(int=1),
    occurrence=0,
    part=None,
):
    s = build_list_snapshot(
        raw,
        document_id=document_id,
        storage_revision=revision,
        source_sha256=sha256(raw).hexdigest(),
    )
    spec = execution() if spec is None else spec
    src = capture_source(raw, s, command=command(s), execution=spec)
    a = prepare_attempt(src, attempt_id=UUID(int=attempt))
    candidates = [
        f
        for f in s.fragments
        if f.text == target and (part is None or f.paragraph_anchor.part_name == part)
    ]
    f = candidates[occurrence]
    finding = issue(
        s, fragment_id=f.fragment_id, span=dict(start=0, end=2, quote=f.text[:2]), suggestion=None
    )
    if related is not None:
        r = next(x for x in s.fragments if x.text == related)
        finding.update(
            type="duplicate", related=dict(fragment_id=r.fragment_id, quote=r.text, status="active")
        )
    out = reply(
        s,
        [finding],
        engine=spec.engine_version,
        models=spec.models_version,
        checked=dict(fragments=len(s.fragments), active=len(s.fragments), skipped_status=0),
    )
    result = capture_result(src, a, reply=canonical(out))
    return src, a, result


def matched(old, new):
    transfers = match_findings(old, new)
    a, b = finding_keys(*old)[0], finding_keys(*new)[0]
    assert len(transfers) == 1
    t = transfers[0]
    assert (t.previous_finding_id, t.previous_key, t.current_finding_id, t.current_key) == (
        a.finding_id,
        a.key,
        b.finding_id,
        b.key,
    )
    assert "evidence" not in repr(t) and "PRIVATE" not in repr(t)
    out = present(*new, hidden_keys=[t.current_key])
    assert out.no_visible_findings and not out.no_findings
    assert match_findings(old, new) == transfers
    return t


def pair(first, second, **kw):
    return records(source(first)[0], **kw), records(source(second)[0], revision=8, attempt=2, **kw)


@pytest.mark.parametrize("change", ["edit", "insert", "remove", "zip_metadata"])
def test_direct_numbered_group_matches_after_unrelated_unstyled_change(change):
    raw = source(body())[0]
    changed = (
        source(body(intro="Changed intro"))[0]
        if change == "edit"
        else source(p("New distant") + body())[0]
        if change == "insert"
        else source(body().removesuffix(p("Distant end")))[0]
        if change == "remove"
        else source(body(), comment=b"changed ZIP comment")[0]
    )
    old, new = records(raw), records(changed, revision=8, attempt=2)
    assert old[0].source_sha256 != new[0].source_sha256
    assert matched(old, new).previous_key != finding_keys(*new)[0].key


@pytest.mark.parametrize(
    "change", ["blank_counter", "neighbor", "styled_prefix", "numbering", "style"]
)
def test_context_change_keeps_equal_literal_quote_visible(change):
    old_raw = source(body())[0]
    kw = {}
    changed = body(intro="Different intro")
    if change == "blank_counter":
        changed = numbered("") + body()
    elif change == "neighbor":
        changed = body().replace("Left context", "Changed neighbor")
    elif change == "styled_prefix":
        changed = body().replace(
            p("Distant intro"),
            "<w:p><w:pPr><w:widowControl/></w:pPr><w:r><w:t>Distant intro</w:t></w:r></w:p>",
        )
    elif change == "numbering":
        kw["definitions"] = DEFS.replace("%1.", "Item %1:")
    else:
        from test_docx_visible_main import style

        kw["styles"] = style("Unused")
    new_raw = source(changed, **kw)[0]
    old, new = records(old_raw), records(new_raw, revision=8)
    assert (
        json.loads(old[2].result_data)["findings"][0]["primary"]["quote"]
        == json.loads(new[2].result_data)["findings"][0]["primary"]["quote"]
    )
    assert match_findings(old, new) == ()


def matrix():
    return table(row(cell(p("Cell left")) + cell(p(EVIDENCE) + p("Cell right"))))


def test_unchanged_table_and_related_cell_shift_after_distant_main_insert():
    old, new = pair(body(matrix()), p("New distant") + body(matrix()), related="Cell left")
    matched(old, new)


@pytest.mark.parametrize("change", ["grid", "sibling", "cell_order"])
def test_changed_table_ancestor_vetoes_same_cell_quote(change):
    t = matrix()
    changed = (
        t.replace('w:w="1000"', 'w:w="2000"', 1)
        if change == "grid"
        else t.replace("Cell left", "Changed cell")
        if change == "sibling"
        else table(row(cell(p(EVIDENCE) + p("Cell right")) + cell(p("Cell left"))))
    )
    old, new = pair(body(t), body(changed))
    assert match_findings(old, new) == ()


@pytest.mark.parametrize("wrapper", ["control", "compatibility", "revision"])
def test_unchanged_nontrivial_ancestor_can_shift_with_its_paragraph(wrapper):
    center = (
        control(p(EVIDENCE), "<w:richText/>")
        if wrapper == "control"
        else selected(p(EVIDENCE))
        if wrapper == "compatibility"
        else '<w:p><w:ins w:id="1" w:author="Synthetic"><w:r><w:t>'
        + EVIDENCE
        + "</w:t></w:r></w:ins></w:p>"
    )
    old, new = pair(body(center), p("New distant") + body(center))
    matched(old, new)


@pytest.mark.parametrize("wrapper", ["control", "compatibility", "revision"])
def test_changed_ancestor_metadata_or_unselected_branch_keeps_finding_visible(wrapper):
    if wrapper == "control":
        center = control(p(EVIDENCE), '<w:richText/><w:tag w:val="one"/>')
        changed = center.replace('w:val="one"', 'w:val="two"')
    elif wrapper == "compatibility":
        center = selected(p(EVIDENCE))
        changed = center.replace("<w:unsupported/>", '<w:unsupported w:changed="1"/>')
    else:
        center = (
            '<w:p><w:ins w:id="1" w:author="Synthetic"><w:r><w:t>'
            + EVIDENCE
            + "</w:t></w:r></w:ins></w:p>"
        )
        changed = center.replace('w:author="Synthetic"', 'w:author="Changed"')
    old, new = pair(body(center), body(changed))
    assert match_findings(old, new) == ()


def note_raw(main, *, content="Note evidence 😀"):
    from test_docx_note_catalog import note
    from test_docx_visible_main import R
    from test_docx_visible_notes import note_xml

    return source(
        main,
        extra_parts={"custom/Foot.xml": note_xml(note(content=p(content)))},
        extra_types={
            "custom/Foot.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
            )
        },
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
    )[0]


def reference_paragraph(text="Referenced requirement", *, after="", marker_only=False):
    from test_docx_visible_notes import ref

    literal = "" if marker_only else "<w:t>" + escape(text) + "</w:t>"
    tail = "<w:t>" + escape(after) + "</w:t>" if after else ""
    return "<w:p><w:r>" + literal + ref() + tail + "</w:r></w:p>"


def test_stable_note_text_transfers_only_with_its_corresponding_reference_parent():
    center = reference_paragraph()
    old = records(note_raw(body(center)), target="Note evidence 😀")
    new = records(
        note_raw(body(center, intro="Changed far intro")), target="Note evidence 😀", revision=8
    )
    matched(old, new)


@pytest.mark.parametrize(
    "change",
    [
        "changed_parent",
        "added_parent",
        "removed_shared_parent",
        "changed_shared_parent",
        "marker_only",
    ],
)
def test_equal_note_text_is_not_hidden_when_its_applying_context_cannot_be_proved(change):
    center = reference_paragraph()
    old_body = body(center)
    changed = body(reference_paragraph("Changed requirement"))
    if change == "added_parent":
        changed = old_body + reference_paragraph("Additional requirement")
    elif change in ("removed_shared_parent", "changed_shared_parent"):
        old_body += reference_paragraph("Second requirement")
        changed = (
            body(center)
            if change == "removed_shared_parent"
            else body(center) + reference_paragraph("Changed second requirement")
        )
    elif change == "marker_only":
        old_body = body(reference_paragraph(marker_only=True))
        changed = body(reference_paragraph(marker_only=True), intro="Changed distant")
    old, new = (
        records(note_raw(old_body), target="Note evidence 😀"),
        records(note_raw(changed), target="Note evidence 😀", revision=8),
    )
    assert match_findings(old, new) == ()


def test_two_unchanged_reference_parents_can_keep_one_shared_note_dismissal():
    main = (
        body(reference_paragraph())
        + p("Gap")
        + reference_paragraph("Second requirement")
        + p("Tail")
    )
    old = records(note_raw(main), target="Note evidence 😀")
    new = records(note_raw(p("New distant") + main), target="Note evidence 😀", revision=8)
    matched(old, new)


def test_note_reference_splits_a_paragraph_without_losing_second_fragment_identity():
    center = reference_paragraph("Before reference", after="After reference")
    old = records(note_raw(body(center)), target="After reference", related="Before reference")
    new = records(
        note_raw(p("New distant") + body(center)),
        target="After reference",
        related="Before reference",
        revision=8,
    )
    matched(old, new)


def image_raw(main):
    from test_docx_visible_inline_images import IMAGE, png
    from test_docx_visible_main import R

    return source(
        main,
        extra_parts={IMAGE: png()},
        extra_types={IMAGE: "image/png"},
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "I", "Type": R + "image", "Target": "picture.bin"},
        ],
    )[0]


def image_paragraph():
    from test_docx_visible_inline_images import drawing

    return "<w:p><w:r><w:t>Before image</w:t>" + drawing() + "<w:t>After image</w:t></w:r></w:p>"


def test_inline_image_boundary_keeps_two_literal_fragments_in_one_group():
    main = body(image_paragraph())
    old = records(image_raw(main), target="After image", related="Before image")
    new = records(
        image_raw(p("New distant") + main), target="After image", related="Before image", revision=8
    )
    matched(old, new)


def test_removing_image_and_changing_segmentation_cannot_reuse_literal_only_match():
    from test_docx_visible_inline_images import drawing

    main = body(image_paragraph())
    old = records(image_raw(main), target="Before image")
    changed = main.replace(drawing(), "</w:r></w:p><w:p><w:r>")
    new = records(image_raw(changed), target="Before image", revision=8)
    assert match_findings(old, new) == ()


@pytest.mark.parametrize("kind", ["table", "note", "image", "control"])
def test_exact_source_revision_and_attempt_replay_supports_all_valid_structures(kind):
    raw = (
        source(body(matrix()))[0]
        if kind == "table"
        else note_raw(body(reference_paragraph()))
        if kind == "note"
        else image_raw(body(image_paragraph()))
        if kind == "image"
        else source(body(control(p(EVIDENCE), "<w:richText/>")))[0]
    )
    target = (
        "Note evidence 😀" if kind == "note" else "After image" if kind == "image" else EVIDENCE
    )
    old, new = records(raw, target=target), records(raw, target=target, revision=8, attempt=2)
    t = matched(old, new)
    assert t.previous_key == t.current_key and t.previous_finding_id != t.current_finding_id


def test_repeated_literal_groups_never_select_an_arbitrary_occurrence():
    old, new = pair(body(), body() + p(EVIDENCE))
    assert match_findings(old, new) == ()


def test_reordering_two_intact_blocks_rejects_every_crossing_candidate():
    a = p("Left A") + p(EVIDENCE) + p("Right A")
    b = p("Left B") + p("Second evidence") + p("Right B")
    old, new = pair(p("Start") + a + b + p("End"), p("Start") + b + a + p("End"))
    assert match_findings(old, new) == ()


def test_identical_numeric_paths_and_text_in_main_and_note_remain_part_scoped():
    main = p(EVIDENCE) + p("Left context") + reference_paragraph() + p("Right context") + p("End")
    old = records(
        note_raw(main, content=EVIDENCE), part="custom/Foot.xml", related="Referenced requirement"
    )
    new = records(
        note_raw(main + p("New distant"), content=EVIDENCE),
        part="custom/Foot.xml",
        related="Referenced requirement",
        revision=8,
    )
    t = matched(old, new)
    assert t.current_finding_id == finding_keys(*new)[0].finding_id
    evidence = json.loads(new[2].result_data)["findings"][0]
    assert evidence["primary"]["slices"][0]["anchor"]["part_name"] == "custom/Foot.xml"
    assert evidence["related"]["slices"][0]["anchor"]["part_name"] == "custom/Main.xml"


@pytest.mark.parametrize("fault", ["source", "snapshot", "request", "result", "counts"])
def test_corruption_is_rejected_even_when_context_or_executor_cannot_match(fault):
    from dataclasses import replace

    from ara.docx_analysis.remapping import RemapError

    old = records(source(body(matrix()))[0])
    src, a, r = records(
        source(body(matrix(), intro="Changed"))[0], spec=execution(models_version="synthetic-2")
    )
    if fault == "source":
        src = replace(src, source_data=b"PRIVATE")
    elif fault == "snapshot":
        value = json.loads(src.snapshot_data)
        value["paragraphs"] = []
        raw = canonical(value)
        src = replace(src, snapshot_data=raw, snapshot_sha256=sha256(raw).hexdigest())
    elif fault == "request":
        a = replace(a, request_data=b"PRIVATE")
    elif fault == "result":
        r = replace(r, result_data=b"PRIVATE")
    else:
        r = replace(r, findings_count=99)
    with pytest.raises(RemapError) as error:
        match_findings(old, (src, a, r))
    assert error.value.code == "corrupt_result" and "PRIVATE" not in str(error.value)


def test_changed_related_context_prevents_hide_even_when_primary_can_match():
    center = p(EVIDENCE) + p("Separate neighbor") + matrix().replace(EVIDENCE, "Cell body")
    changed = center.replace('w:w="1000"', 'w:w="2000"', 1)
    raw, new_raw = source(body(center))[0], source(body(changed))[0]
    matched(records(raw), records(new_raw, revision=8))
    old, new = records(raw, related="Cell left"), records(new_raw, related="Cell left", revision=8)
    assert match_findings(old, new) == ()


def test_bounded_correspondence_checks_both_full_structured_snapshots():
    from ara.docx_analysis.remapping import RemapError, RemapLimits

    old, new = pair(body(matrix()), p("New distant") + body(matrix()))
    with pytest.raises(RemapError) as error:
        match_findings(old, new, limits=RemapLimits(max_paragraphs=1))
    assert error.value.code == "limit_exceeded"


def resolution_input(old, new, *, limit=8388608, hidden=True):
    from ara.docx_review_preferences._models import Origin, PreferencesState
    from ara.docx_review_resolution._models import DismissalRef, ResolutionInput, ResolutionLimits

    a = finding_keys(*old)[0]
    state = PreferencesState(
        old[0].document_id, 1 if hidden else 0, (), True, False, (a.key,) if hidden else ()
    )
    first, target = Origin(UUID(int=10), *old), Origin(UUID(int=20), *new)
    decisions = (
        (DismissalRef(a.key, first.run_id, first.result.result_sha256, a.finding_id, 1),)
        if hidden
        else ()
    )
    return ResolutionInput(
        state,
        target,
        (first,) if hidden else (),
        decisions,
        ResolutionLimits(max_text_characters=limit),
    )


def test_resolution_aggregates_structured_alias_without_mutating_original_decision():
    from ara.docx_review_resolution._resolve import resolve

    old, new = pair(body(matrix()), p("New distant") + body(matrix()))
    inputs = resolution_input(old, new)
    out = resolve(inputs)
    assert out.state == inputs.state and out.decisions == inputs.decisions
    assert out.hidden_keys == (finding_keys(*new)[0].key,) and len(out.aliases) == 1
    assert out.aliases[0].origin_keys == inputs.state.hidden_keys
    assert present(*new, hidden_keys=out.hidden_keys).no_visible_findings


@pytest.mark.parametrize("hidden", [False, True])
def test_resolution_work_budget_counts_generated_labels_and_suffix_for_each_source_pass(hidden):
    from ara.documents.storage import DocumentError
    from ara.docx_review_resolution._resolve import resolve

    raw = source(body())[0]
    old, new = records(raw), records(raw, revision=8, attempt=2)
    snapshot = json.loads(new[0].snapshot_data)
    literal = len(snapshot["analysis_text"])
    cost = literal + sum(len(i["label"]) + (i["suffix"] != "nothing") for i in snapshot["lists"])
    passes = 3 if hidden else 1
    assert cost > literal
    exact = resolution_input(old, new, limit=passes * cost, hidden=hidden)
    assert bool(resolve(exact).hidden_keys) is hidden
    with pytest.raises(DocumentError) as error:
        resolve(resolution_input(old, new, limit=passes * cost - 1, hidden=hidden))
    assert error.value.code == "preferences_resolution_limit" and error.value.status == 413


def wrapped_body(raw):
    import io
    import zipfile

    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as old, zipfile.ZipFile(output, "w") as new:
        for entry in old.infolist():
            data = old.read(entry.filename)
            if entry.filename == "custom/Main.xml":
                # Preparation correction: package grammar requires a direct body.
                # Wrap its individual logical paragraphs, keeping the frozen
                # correspondence assertions. The historical test name is broader.
                import re

                data = re.sub(
                    rb"(<w:p>.*?</w:p>)",
                    lambda match: (
                        b'<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/'
                        b'markup-compatibility/2006"><mc:Choice Requires="w">'
                        + match.group(1)
                        + b"</mc:Choice></mc:AlternateContent>"
                    ),
                    data,
                    flags=re.DOTALL,
                )
            new.writestr(entry, data)
    return output.getvalue()


def test_valid_compatibility_wrapper_above_main_body_does_not_require_direct_raw_body():
    old = records(wrapped_body(source(body())[0]))
    new = records(wrapped_body(source(p("New distant") + body())[0]), revision=8)
    matched(old, new)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_unchanged_final_section_keeps_context_despite_shifted_absolute_position(strict, encoding):
    raw = source(body() + "<w:sectPr/>", strict=strict, encoding=encoding)[0]
    other = source(p("New distant") + body() + "<w:sectPr/>", strict=strict, encoding=encoding)[0]
    matched(records(raw), records(other, revision=8))


def test_paragraph_section_context_is_valid_but_cross_source_transfer_stays_conservative():
    section = "<w:p><w:pPr><w:sectPr/></w:pPr><w:r><w:t>Section boundary</w:t></w:r></w:p>"
    raw = source(body(section + p(EVIDENCE)) + "<w:sectPr/>")[0]
    changed = source(p("New distant") + body(section + p(EVIDENCE)) + "<w:sectPr/>")[0]
    old, new = records(raw), records(changed, revision=8)
    assert match_findings(old, new) == ()
    matched(old, records(raw, revision=8, attempt=2))


def test_review_raw_body_wrapper_stays_outside_existing_package_grammar():
    import io
    import zipfile

    from ara.docx_package import DocxError

    raw = source(body())[0]
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as old, zipfile.ZipFile(output, "w") as new:
        for entry in old.infolist():
            data = old.read(entry.filename)
            if entry.filename == "custom/Main.xml":
                data = data.replace(
                    b"<w:body>",
                    b'<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/'
                    b'markup-compatibility/2006"><mc:Choice Requires="w"><w:body>',
                )
                data = data.replace(b"</w:body>", b"</w:body></mc:Choice></mc:AlternateContent>")
            new.writestr(entry, data)
    with pytest.raises(DocxError) as error:
        records(output.getvalue())
    assert error.value.code == "invalid_package"


def test_review_endnote_keeps_exact_target_kind_and_reference_parent():
    from test_docx_visible_notes import fixture as notes_fixture
    from test_docx_visible_notes import ref

    center = "<w:p><w:r><w:t>Referenced requirement</w:t>" + ref(kind="endnote") + "</w:r></w:p>"
    old = records(notes_fixture(body=body(center))[0], target="End")
    new = records(notes_fixture(body=p("New distant") + body(center))[0], target="End", revision=8)
    matched(old, new)


@pytest.mark.parametrize(
    "kind,target,identity", [("header", "Header", "H"), ("footer", "Footer", "F")]
)
def test_review_unchanged_section_story_matches_after_main_text_edit(kind, target, identity):
    from test_docx_section_catalog import reference, section
    from test_docx_visible_stories import fixture as stories_fixture

    final = section(reference(identity, kind))
    old = records(stories_fixture(body=p("Original body") + final)[0], target=target)
    new = records(stories_fixture(body=p("Changed body") + final)[0], target=target, revision=8)
    matched(old, new)


@pytest.mark.parametrize("suffix", ["tab", "space", "nothing"])
def test_review_resolution_counts_unicode_labels_and_exact_suffix_cost(suffix):
    from ara.documents.storage import DocumentError
    from ara.docx_review_resolution._resolve import resolve

    definitions = DEFS.replace("%1.", "😀" * 128 + " %1").replace(
        "<w:lvlText", f'<w:suff w:val="{suffix}"/><w:lvlText'
    )
    raw = source(body(), definitions)[0]
    old, new = records(raw), records(raw, revision=8)
    snapshot = json.loads(new[0].snapshot_data)
    item = snapshot["lists"][0]
    cost = len(snapshot["analysis_text"]) + len(item["label"]) + (suffix != "nothing")
    assert item["suffix"] == suffix and len(item["label"]) < len(item["label"].encode())
    assert resolve(resolution_input(old, new, limit=cost, hidden=False)).hidden_keys == ()
    with pytest.raises(DocumentError) as error:
        resolve(resolution_input(old, new, limit=cost - 1, hidden=False))
    assert error.value.code == "preferences_resolution_limit"
