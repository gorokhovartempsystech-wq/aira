# D03-18A4 — review presentation client completed

5 November 2026, baseline a00af86. New pinned review transport and inert review
coordinator load specific/latest successful results and expose detached state with
fixture label, original no-findings versus filtered empty view, and RAM freshness.
Filters/questions/hidden visibility persist through exact revisioned commands; lost
ACK repeats identical serialized bytes. Known conflicts require explicit refresh;
failed refresh after confirmed command does not repeat that write. Late replies
cannot resurrect a disposed client. No quote search, document edit or inference.

Initial red: 9 missing-module failures. First pure: 9 passed. Actual owned macOS
Node Fetch plus first pure suite: 10 passed, 2 warnings, 58.51s. Both plain and
merged-table DOCX exercised analysis/load/hide/show/filter/clear, stale RAM after
edit and restored freshness after undo. Untouched DOCX parts remain byte-exact.
Final pure edge suite: 13 passed, including strict hash validation, true no-findings,
transport deadline and late command after disposal. Ruff check/format passed.

Full scripts/check.sh passed: **6966 passed, 45 skipped, 78 warnings,
24 subtests, 1390.51s, exit 0**. Main database schema/count snapshot unchanged.
Acceptance closed. Old source/tests,
SQL, runner and dependencies unchanged. Final frontend, real model, Windows-native
and visual Word/release gates remain external. Next: open/recovery/tabs/safe close.
