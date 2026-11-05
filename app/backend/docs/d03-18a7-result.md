# D03-18A7 — complete workflow accepted

5 November 2026, baseline4282fbc. Production connected importer/workspace clients
now run through one reproducible create/import/edit/undo/redo/tabs/autosave/analysis/
hide/filter/close/restart/recover/recheck/export/reimport workflow on three synthetic
DOCX files. Separate host lifetimes require activate then fresh check through the
synthetic licensing transport. Real model quality and deployed licensing are not
claimed. Exported package hashes/text/untouched auxiliary parts are asserted.

Initial red:1 missing-driver failure. First real workflow found simultaneous autosave
failure: one checkpoint acknowledged, two editor clients uncertain. Diagnostic run
recorded exactly those states. Existing backend EditorTransport allows one request;
independent per-tab lanes did not coordinate this host capacity. Contract narrowed
to a shared bounded FIFO in connected workspace composition, preserving exact requests
and releasing on error. Analysis Stop bypasses the ordinary queue. No backend or old
test/time-limit changes. New queue acceptance red3, then3 passed (FIFO/error/capacity).

The actual full workflow then passed:1 passed,2 warnings,37.77s. The command is
`bash scripts/check_docx_workflow.sh`. Synthetic outputs were emitted under
`.runtime/aira-workflow-demo/run-z87zUh`:new.docx,plain.docx,table.docx,report.json.
All three exports were reimported/reopened. Three simultaneous autosave callbacks
use advanced test time but actual HTTP checkpoint/DB writes. AIRA auxiliary content
was not inserted into the exports. Native Word visual layout was not verified.

Final bash scripts/check.sh:7009 passed,45 skipped,76 warnings,24 subtests,
1478.45s,exit0. Main schema/revision/counts equal A6 baseline; no row contents read.
No unrelated changes, old tests, SQL, runner or dependency edits. This closes the
independent client/backend integration sequence, not the external
UI/real-model/Windows/visual-Word/TLS/signing release gates. Handoff:docx-workflow-handoff.md.

Remaining independent integration cycles:0. Real release gates listed in the handoff.
