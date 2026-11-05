# D03-18A5 — document workspace accepted

5 November 2026, baseline 2857bc6. New workspace and bounded transport compose the
existing editor/analysis/review clients. One tab per document, global opening lane,
explicit draft recovery and pending-save reconciliation, exact open/close retries,
focus without actor destruction, checkpoint-before-close and durable proof after
lost close ACK. Managed client lifecycle is private; analysis Stop stays available.

Initial red: 9 missing-module failures. First implementation exposed two mistakes
in the new fake checkpoint preparation: observed checkpoint revision was not moved
with its acknowledged revision. Fixed that preparation, keeping assertions. Native
script initially had a missing closing brace; fixed only its syntax. No old tests
were changed. Initial pure 9 passed; final pure review 12 passed.

Owned macOS/Node Fetch plus initial pure cases: 10 passed, 2 warnings, 17.51s. Two
plain/merged-table documents edited; actual lost open/close replies retried; both
closed and host restarted with a fresh online license check; explicit recovery
preserved each prefix exactly once. Saved review restored as stale against new draft
RAM. Saves/exports retained untouched auxiliary DOCX parts. Ruff check/format passed.

Final full gate and main schema/count check are recorded below. Old tests, SQL,
runner and dependencies unchanged; narrow Word codec correction described below.
Final UI/native shell must await closeAll, not rely on browser unload. Real model,
Windows-native, visual Word and release gates remain external. Next: DOCX files.

First full gate: 1 failed, 6978 passed, 45 skipped, 24 subtests, 1487.05s.
The unchanged supervisor publication-rollback test [False] reached failed before
its synthetic platform launch (expected launches=1, observed 0). New workspace
cases passed. No causal diagnosis from that first traceback; do not call it fixed.
The complete supervisor module then passed 36 cases in 17.06s. Twenty independent
process runs of both publication-fault branches passed (40 checks). A duplicate
selector attempt ran only two cases and is not counted as stress repetition.
Full gate is being repeated with an ignored diagnostic plugin that only reports
safe status/error/platform trace for a zero-launch result. No production or old
acceptance code changed, and no retry, skip or relaxed assertion was added.

The first diagnostic rerun was invalid: the temporary wrapper assumed every native
platform had a synthetic `launches` field and caused AttributeError in an old native
test. Interrupted that run (1 failed/714 passed/2 skipped, exit 130); it is not a
product failure or accepted gate. Replaced the ignored plugin with a passive pytest
failure-report hook: it changes no functions or execution and only appends the
synthetic trace for the exact supervisor test module. Native regression plus both
publication branches passed with this hook (3 passed, 3.88s). Full rerun follows.

The next passive diagnostic run hit the old six-Word analysis waiter (12s), not
GET review's 5s timeout. Interrupted it for immediate diagnosis; no accepted gate.
A deterministic new regression showed restore_source rebuilding a Word source twice
and prepare_attempt three times (2 failed/1 passed before implementation). The narrow
contract now permits _records.py to continue a freshly reconstructed, manifest-checked
WordSnapshot through shape/provenance/limit validation and private request encoding.
Detached public inputs still require independent original-byte validation. No persistent
cache or timeout changes. New and existing codec/review regressions: 32 passed,114.97s.
Native Word + workspace + complete supervisor module:54 passed,2 warnings,183.43s.
The original isolated zero-launch supervisor failure remains without a demonstrated
cause; these results do not claim to fix that separate observation. Final full gate
is running after the Word restoration correction.

Final acceptance: bash scripts/check.sh completed exit 0, 6982 passed,45 skipped,
79 warnings,24 subtests,1338.36s. Main schema/revision/counts equal A4 baseline;
no user row contents read. The original Word timeout and additional analysis-wait
regression pass with unchanged old time limits. The earlier isolated supervisor
failure was not reproduced in 40 branch checks or this final full gate; its cause
is not claimed established. No automatic retry was added to the suite.
Next: D03-18A6 create/import/confirmed export, then A7 reproducible whole scenario.
