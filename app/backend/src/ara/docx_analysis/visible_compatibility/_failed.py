"""An early failed context cannot expose an invented ready or absent proof."""

from dataclasses import replace
from hashlib import sha256

from ara.docx_analysis.compatibility_contexts._models import STYLE_PROFILE
from ara.docx_analysis.visibility._read import context
from ara.docx_analysis.visible_main._canonical import coverage_key, digest
from ara.docx_analysis.visible_main._models import POLICY, VisibleCoverage, budget
from ara.docx_analysis.visible_notes._models import NoteSnapshot


def failed(
    prepared, document_id, storage_revision, limits, profile, *, style_profile=STYLE_PROFILE
):
    source, issue = prepared.source, prepared.contexts.issues[0]
    budget(len(source.entries) + 1, limits.max_coverage_items)
    coverage = [
        VisibleCoverage("blocked", "compatibility_context_blocked", entry.name, None, None)
        for entry in source.entries
    ]
    coverage.append(
        VisibleCoverage(
            "blocked",
            issue.code,
            issue.anchor.part_name if issue.anchor is not None else source.main_part,
            issue.anchor,
            None,
        )
    )
    styles = context(
        source.sha256, "blocked", code="compatibility_context_blocked", profile=style_profile
    )
    result = NoteSnapshot(
        document_id,
        storage_revision,
        source.sha256,
        profile,
        POLICY,
        source.main_part,
        styles,
        (),
        (),
        (),
        "",
        tuple(sorted(coverage, key=coverage_key)),
        False,
        sha256(b"").hexdigest(),
        "",
        (),
    )
    return replace(
        result, snapshot_sha256=digest(result, limits.max_manifest_bytes, omit_hash=True)
    )
