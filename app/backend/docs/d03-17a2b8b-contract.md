# D03-17A2b8B — style-list review through the owned desktop

5 November 2026. Baseline: B8A `e5d494c`. F06–F09/F11/F12 vertical integration of the
source-proven StyleListSnapshot. Synthetic fixture2 only; no real weights, GUI or release claim.

## Paths and gates

Thirteen existing source hooks, preserving the three old profiles:
- src/ara/docx_analysis/storage_codec/_records.py: exact new DTO/profile/build/review dispatch and generated cost;
- src/ara/docx_analysis_worker/structured_fixture/_api.py: fourth exact wire/profile pair;
- src/ara/docx_analysis_worker/structured_fixture/_context.py: fixed style-list shape policy, old readers unchanged;
- src/ara/docx_analysis_worker/supervisor/runtime.py and _admission.py in that directory: closed new source-profile choice;
- src/ara/docx_analysis/presentation/_view.py: result4/view4 context pairing;
- src/ara/docx_analysis/remapping/_match.py: verified style-list matching dispatch;
- src/ara/docx_analysis/remapping/structured/_groups.py: fixed new-profile physical style provenance keys;
- src/ara/docx_review_resolution/_resolve.py: generated cost for the new profile;
- src/ara/desktop/composition/_models.py and _wiring.py in that directory: explicit style_lists_fixture mode;
- src/ara/docx_analysis_api/_wire.py and src/ara/docx_review_api/_wire.py: fourth nested metadata version.

New src/ara/docx_analysis/style_list_review/, src/ara/docx_analysis_runs/style_lists.py,
src/ara/docx_analysis_worker/supervisor/style_lists_fixture.py,
src/ara/docx_analysis_worker/structured_fixture/_style_bindings.py and
src/ara/docx_analysis/remapping/structured/_style_numbering.py; new contracts
contracts/docx-review-v4.json, contracts/docx-review-view-v4.json; new acceptance
 test_docx_style_list_integration.py, test_docx_style_list_runtime.py,
 test_desktop_style_list_review.py; docs/d03-17a2b8b-contract.md, docs/d03-17a2b8b-result.md,
docs/docx-style-list-integration.md, docs/development-queue.md and ignored .runtime.
Exactly one old-test change: in test_desktop_structured_review.py function
 test_http_nested_version_metadata_describes_both_supported_public_shapes,
add version4 to its two expected arrays, keeping all previous versions/assertions. Freeze this
additive expectation with new acceptance. No other old tests/source paths/schemas/SQL/native
children/transport/dependencies/runner/tasks/progress/user files or external publication.

Freeze/red, target/review/regression, old exact-byte probes, full scripts/check.sh plus explicit
builder Ruff, pre/post gate hashes, readonly mainV8 comparison and selective local commit.
New-test preparation-only corrections may be documented if frozen assertions remain intact.
No implementation/test/frozen-contract changes during full gate. After completion continue
independently within the user's explicit autonomous authorization.

## Versioned review and source preservation

style_list_review exposes prepare_style_list_review / validate_style_list_reply using the
fixed new mapper and unchanged atomic reply algorithm. Wire docx-review/4, view
 docx-review-view/4, profile docx-analysis/final-visible-style-lists-v1. Lists contain all
StyleListItem fields (including numbering_source, style_reference_anchor, style_chain,
level_style_anchor), notes and literal fragments retain their prior meaning. Generated markers
cannot become literal evidence. New standalone closed schemas retain bounded anchors and chain
max128/unique; label limits/level0..8/four formats stay. JSON shape is not XML authority.

Codec format1/SQL remain unchanged. Exact DTO dispatch and stored profile choose the fixed
builder; original source, canonical snapshot, attempts and replies are rederived and compared,
including empty-map proof. Generated text counts against admission and resolution limits.
New saved admission always uses the new profile even for a plain file, without adaptive fallback.
Historical replay/retry retains each original accepted profile independent of current edits.

## Fixed fixture policy and native execution

Fixture2 admits only exact four wire/profile pairs; execution identity and native review2
transport remain unchanged. New fixed read_style_lists policy builds on the outline bounds.
Every new list record has the four additional required fields; old pairs reject those fields.
Direct records require properties below the paragraph, empty chain and null style anchors.
Style records require a nonempty unique chain of at most128 physical anchors in one style part,
properties below the final owner, selector absent or below the paragraph, level binding in the
same numbering part as definition/instance. Style and numbering parts are distinct from the
paragraph part. Aggregate chain entries <=100000. These are bounded shape checks only; parent
source reconstruction proves the actual style graph, default selection and numbering semantics.
No cross-profile interpretation or caller registry. Mixed/unknown pairs reject atomically.

New create_style_list_fixture_supervisor returns the same issued Supervisor with the fixed new source_profile
(the existing argument, no new policy API). Native macOS acceptance uses real fixture2 child/owned lifecycle; Windows
child-body portability does not prove native Windows startup/drain. No containment changes.

## Hides, presentation and desktop

View4 carries the complete context through filters/hide/show without private keys/provenance.
Hides transfer only after full source/result proof and exact profile/model identity. Extend the
structured matcher for the new profile only: direct properties stay paragraph-relative; style
properties/chain/level binding retain physical part/path, selector stays paragraph-relative.
Include numbering_source and every new provenance field in the semantic key. Keep the existing
non-main part seal, so changed style/numbering bytes cannot reuse a hide even if the label is
unchanged. Distant ordinary main-story edits can retain one; changed text/counter/style binding,
ambiguous context and profile changes cannot. Old-profile keys/bytes stay identical.

Explicit inert config style_lists_fixture rechecks mode before resources and chooses a fixed
lazy factory. Existing modes/default, routes/HTTP1 envelopes, online license and owned Home/PG
shutdown stay unchanged. Application acceptance: import style-bound parent/child, check/hide,
full close/restart/new online grant, pinned retry/show, exact export; distant edit retains hide,
relevant edit restores finding. Rehashed provenance corruption, forged child context, current
source changes, four-profile historical retries, native stop and old exact bytes are covered.

Real ML package, Anya's UI, native Word/Windows proof and signed release remain independent gates.
