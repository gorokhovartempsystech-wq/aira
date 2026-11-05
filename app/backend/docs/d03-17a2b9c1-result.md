# D03-17A2b9C1 — opt-in table editor prerequisite complete

5 November 2026. Baseline `1aa0dbe`, acceptance freeze `c787bad`.
Red **24 failed,2 warnings /2.06s**. First pure18 passed1.84s; HTTP6 passed3.87s.
Review caught a new implementation keyword mismatch in body paste; fixed before adding
body-paste parity acceptance. No frozen assertion/preparation was changed. Eleven pure
review cases and one owned desktop case were appended. Final pure **29 passed /2.81s**.
Combined new and prior editor/checkpoint/history acceptance **353 passed,3 warnings /46.41s**
(36 new,317 prior). Frozen B9B integration plus its metadata test **40 passed,2 warnings
/292.82s**. B9B's prior codec/review regression270 passed45.79s and four old-profile byte probes
remain exact. Its initial real failures are retained in its [result history](d03-17a2b9b-result.md).

The explicit TableEditorSession selects existing cell paragraphs without fabricating body text.
Simple cell insertion/replacement, soft breaks, exact undo/redo and checkpoint/recovery/save
work through the existing HTTP protocol. Empty/nested/merged cells, Unicode, lexical paragraph
exterior and run formatting are tested. An owned licensed macOS fixture desktop edited a merged
cell, checked the saved literal and exported all untouched auxiliary parts exactly. Legacy body
editor/default refusal remains mandatory. No SQL/wire schema/dependency or runner changes.

`bash scripts/check.sh`: **6849 passed,45 skipped,81 warnings,24 subtests passed /1280.48s**,
exit0. Recursive Ruff957 files plus explicit builder check/format5 passed. All1060 gate hashes
match;1024 prior B9A inputs outside17 combined B9B/C1 allowed paths stayed unchanged. Both
acceptance freezes and contracts remain intact, with review cases appended only. Readonly mainV8
schema/revision/counts match B9A; no row content read. No publication or unrelated user edits.

Cycle complete; B9B's table-only gate is also resolved. [Usage and limitations](docx-table-editor.md).
Cell structural/grid manipulation, multiline/tab cell paste and complex guarded content are not
claimed. Real model package, final GUI, native Word/Windows and release acceptance remain separate.
Next D03-18A1: DOCX client command/autosave coordination, then actual transport integration.
