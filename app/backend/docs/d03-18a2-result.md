# D03-18A2 — implementation saved; full acceptance remains open

5 November2026. Work stopped at the user's explicit request. Baseline4b1f1ce,
acceptance freezeabb6a9c. Do not start A3 or claim this cycle fully accepted.

The pinned editor Fetch transport is implemented. It binds one trusted loopback origin,
capability and actor; preserves serialized commands; refuses redirects/foreign paths;
bounds request/reply work and total30second request lifetime. Late responses, cancelled
callbacks and cleanup failures cannot create a fresh write or replace its acknowledgement.
Errors do not expose capabilities or document text. [Usage](docx-client-transport.md).

Actual red **26failed,2warnings /2.49s**. First pure25passed0.86s; owned macOS integration
1passed2warnings15.05s. Real NodeFetch with the licensed desktop proved lost-ACK exactretry,
virtual two-minute autosave with actual durableHTTPcheckpoint, restart/freshlicensecheck,
explicit recovery and save/export for plain and merged-cell Word files. Invalid capability
cannot edit; the prefix appears once and all untouched auxiliary DOCX parts remain exact.

Independent review11cases first gave1failed/10passed: explicit null dependency overrides
incorrectly selected defaults. Fixed only new source; undefined is now the sole default case.
Other review cases cover UTF8 budgets/chunks, stream failures, stale callbacks/responses,
independent actors and a real307 redirect that never reaches the second local server.
No frozen acceptance changes; review cases appended only. New plus prior client/access/server
regression **196passed,2warnings /18.65s**. Final pure **36passed /1.16s**; one owned case
excluded there. Ruff check/format passed; both general-gate lint stages passed as well.

Two `bash scripts/check.sh` attempts hit the unchanged old test
`test_desktop_word_review::test_word_hide_close_fresh_license_retry_show_and_exact_export`:
GETanalysis-review after successful old-run retry exceeds its existing5second HTTP timeout.
Both were interrupted after the observed failure to obtain diagnostics and stop work:
first1failed1193passed2skipped3warnings453.00s; final1failed1175passed2skipped3warnings446.50s;
exit2 means interrupted, not a successful full gate. The isolated unchanged test passed
1test2warnings43.92s. This does not resolve the repeated suite failure or establish its cause.
No timeout was raised, test skipped or old implementation changed to hide the failure.
The last fully green repository gate remains A1:6897passed45skipped24subtests1283.53s.

All1071 frozen gate input hashes still match; all1066 previous inputs are untouched. MainV8
schema/revision/counts match A1 after cleanup; no row contents read. Unrelated user edits,
runner, dependencies, SQL and old tests/source are unchanged. No remote publication.

Next action on explicit resume: investigate and fix the demonstrated Word review latency,
then close the full acceptance gate. Keep A2's completed functional checks, but retain this
open gate in status. Five further functional integration blocks are estimated in the
[queue](development-queue.md); realML/finalGUI/nativeWindows/Wordvisual/release are not proven.
