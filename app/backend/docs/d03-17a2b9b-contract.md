# D03-17A2b9B — ordinary Word checks through the owned desktop

5 November 2026. Baseline `9c02800`. F06–F09/F11/F12: integrate B9A's fixed WordSnapshot. Real inference,
GUI, native Windows composition, Word rendering and signed releases remain separate.

Twelve existing source hooks: storage_codec/_records.py; structured_fixture/_api.py;
supervisor/runtime.py and _admission.py; presentation/_view.py; remapping/_match.py and
remapping/structured/_groups.py; docx_review_resolution/_resolve.py; desktop/composition/
_models.py and _wiring.py; docx_analysis_api/_wire.py and docx_review_api/_wire.py (under src/ara,
with docx_analysis/docx_analysis_worker prefixes matching existing B8B modules).
New src/ara/docx_analysis/word_review/, src/ara/docx_analysis_runs/word.py,
src/ara/docx_analysis_worker/supervisor/word_fixture.py, contracts/docx-review-v5.json and
contracts/docx-review-view-v5.json; new acceptance test_docx_word_integration.py,
test_docx_word_runtime.py, test_desktop_word_review.py; docs/d03-17a2b9b-contract.md,
docs/d03-17a2b9b-result.md, docs/docx-word-integration.md, docs/development-queue.md; .runtime.
One precise old test preparation: the two nested-version arrays in
 test_desktop_structured_review.test_http_nested_version_metadata_describes_both_supported_public_shapes
add version5, retaining every prior version and assertion. Freeze this addition before red.
No other old paths/tests/schemas, SQL, migrations, dependencies, runner/tasks/progress/defaults,
child processes or native transport changes. No external publication.

Freeze/red, target/review/regression and old four-profile exact bytes; full scripts/check.sh
plus explicit builder Ruff, gate hashes and readonly mainV8 comparison; selective local commit.
New-test preparation corrections may be documented with frozen assertions retained. No source/
acceptance/frozen-contract mutation during the full gate; continue next autonomous cycle after.

Fixed WordSnapshot review5/view5 uses the existing full style-list/notes context and unchanged
atomic reply validation, with the new original-source mapper. Closed standalone schemas have
exact profile/version and all existing bounds; JSON shape never replaces XML proof. Codec
format1 retains exact source/snapshot and rederives the matching fixed profile. Historical
retry preserves all five accepted profiles independently of current bytes/mode. Generated label
cost stays bounded for admission and resolution. Unsupported input never queues or falls back.

Fixture2 admits exactly the fifth wire/profile pair, reusing the existing closed style-list
context validator. No new model identity, child mode or arbitrary policy registry. The existing
native review2 transport, lifecycle, stop/deadline and source-pinned retry apply unchanged.
Word fixture supervisor uses explicit fixed admission; desktop mode word_fixture is inert,
validated before resource ownership and lazily selects that supervisor. Legacy default unchanged.

View5 retains list/note context, public privacy, filter and persisted hide semantics. New-profile
remapping uses all style physical provenance and existing non-main source seal; distant ordinary
text changes may retain a hide, whereas changed style/auxiliary bytes, changed literal/context
or profile changes cannot. Never upgrade old stored meaning or erase its hide decision.

Acceptance covers six independent ordinary-template packages through codec/fixture/view;
rehashed source/context forgery; wrong version/profile; generated labels not literal evidence;
five-profile historical native retry; stopped checks without results; actual macOS licensed
owned Home+PG HTTP import/check/hide/close/fresh online grant/retry/show/exact export. Manual
text editing/export preserves all untouched auxiliary ZIP parts and the result cites the saved
new literal. Check new plain and new AIRA documents explicitly use the new profile without
adaptive fallback. Native Windows child-body portability is not native Windows acceptance.
