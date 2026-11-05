# D03-18A6 — file clients accepted

5 November 2026, baseline 96bdfdb. New bounded file transport and importer/exporter;
workspace composes per-actor export and blocks conflicting actions. Stop remains
available independently during pending export. Create has no Content-Type/body;
imports retain copied bytes and one UUID on retry. Saved export uses the acknowledged
save UUID/result counters, verifies binary media/hash/revision, and returns bytes
for explicit shell destination handling. No fallback to latest/working copy.

Initial red:17 missing-module failures. First pure:17 passed. Owned licensed native
macOS/Node Fetch plus workspace regression:31 passed,2 warnings,29.66s. Created one
new template document, imported plain/merged-table Word files, edited/exported all;
lost import/save/download responses replayed exactly. Untouched auxiliary package
parts equal original; edited prefix occurs once. Added safe-integer revision, wrong
copy-kind/revision and uncertain-save cancellation checks; final pure22 passed.
No old test/backend route/schema/dependency changed. Only approved workspace hooks.

Final scripts/check.sh:7005 passed,45 skipped,79 warnings,24 subtests,1382.41s,
exit0. Main schema/revision/counts equal A5 baseline. No row contents read. Real frontend
and native save picker, visual Word, real model, Windows/release gates external.

Next and final independent integration cycle: D03-18A7 reproducible whole scenario.
