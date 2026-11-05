# D03-17A2b6c3 — source-verified structured presentation

5 November 2026. Baseline: verified C2 `7d13970`.
One feature (F08/F09/F12): retain source-proven list/note context in the filtered review
presentation. No product-scope change.

## Paths and verification

Exactly one old source hook: src/ara/docx_analysis/presentation/_view.py.
New contracts/docx-review-view-v2.json; tests/acceptance/test_docx_structured_presentation.py.
This contract/result, docs/docx-structured-presentation.md, docs/development-queue.md,.runtime.
No old tests/contracts/SQL/models/migrations/source codecs/finding IDs or dismissal keys,
HTTP routes/schema installers, remapping/resolution, worker/desktop/runner/tasks/dependencies.
Freeze/red, implementation/review/regression, full check.sh, frozen hashes/read-only mainV8,
selective local commit. New-test preparation-only corrections may be documented with frozen
assertions unchanged; no source/test/frozen-contract edits during full gate. No publication.

## Behavior

Same public present/finding_keys/Presentation API. Full storage codec revalidation before
view construction remains obligatory even when all findings are hidden/filtered or no findings
were returned. Fixed verified result schema docx-review/2 selects docx-review-view/2 and adds
required document_context verbatim from the validated envelope. Legacy docx-review/1 yields
byte-identical old view1 with no new property. No caller-supplied view/source version, no fallback
for unknown source profiles; restore_result remains authority. No second parse/rebuild/inference.

Context contains all lists/note_references of the pinned source, including entries with no
finding or no visible literal fragment; filtering findings must not alter that source context.
Labels stay metadata, never prepended to quotes, offsets or slices. Source paths, literal
primary/related evidence, coverage, questions and provenance retain existing wire types.
Hidden questions/findings follow existing preferences; show_questions=False removes only
questions, not context. No private_provenance/rules/suggestions/hidden keys/raw source/hidden
text in the public view. Dismissal keys keep the same domain/algorithm: exact source hash
already binds source-derived structure. A changed label/source or executor changes the key;
identical source bytes across revision/attempt preserve it. No cross-source correspondence
claim in this cycle. Fixture results stay fixture and never assert real no-findings.

All existing output bounds/counts/hash/canonical encoding and content-safe errors preserved.
Required context contributes to MAX_VIEW, with no truncation. Presentation remains pure,
with no persistence/filesystem/network/secret lookup or module-import side effects.

## View2 schema and acceptance

New standalone JSON Schema2020-12, urn:aira:docx-review-view:2. Closed top-level view shape,
all actual keys required; fixed structured profile/policy, source/evidence/provenance/context
and coverage definitions identical to review2. Questions add required visible_finding_ids
with existing finding-ID grammar. Preferences/counts/hidden IDs/fixture/no-visible flags typed
and bounded; no raw/private fields. Every reference resolves locally. This shape schema does
not establish source authenticity or cross-field correctness; source codec and behavior tests do.
No dependency installation; optional external metaschema validation must be reported separately.

Positive synthetic lists/notes/template/empty/no-context cases; default/hide/show/filter/questions
and shared question origins preserve complete context and original records. Literal evidence
still maps to original Unicode/hidden-gap slices. Revisions/attempts, changed label/executor
isolate dismissal keys. Rehashed context tampering in source/request/result and invalid counts
remain corrupt_result even under all-hidden view. Context contributes to output bound. Legacy
bytes/keys regression and schema self-containment/common definitions, source contract unchanged.
Next: separate structured correspondence/resolution, then HTTP/desktop integration. Native
Windows/Word, real ML package and release UI/signing/TLS gates remain external.
