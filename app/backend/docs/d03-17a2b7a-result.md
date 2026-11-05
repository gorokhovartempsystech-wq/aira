# D03-17A2b7A — direct outline source reader complete

5 November 2026. Baseline `53a8112`, freeze `d15094d`. Source grammar and selected wrapper
fixtures were preflighted before freeze; the plain-control case was placed around a paragraph
inside a cell, within its existing grammar. Red **56 failed /0.63s**. First implementation
**56 passed /0.63s**; review added eight cases, final target **64 passed /0.66s**.
Original frozen acceptance remains an exact byte prefix; no preparation correction after
freeze. Source-family regression **624 passed /3.46s** (includes the new64).

New fixed OutlineSnapshot source profile reads direct levels0–8, independent per-instance
counters, default/custom/never restart, replacement levels and start overrides, decimal/bullet/
upper/lower Roman and legal decimal labels. Literal source mapping stays separate. Review
covers level8 default-vs-explicit triggers, note context/non-main numbering refusal, raw bounds
before selected DOM, changed source and wrong quote/manifest budgets. No existing source changed.

`bash scripts/check.sh`: **6533 passed,45 skipped,80 warnings,24 subtests passed /834.70s**,
exit0; recursive Ruff900 files plus explicit builder check/format5. All985 gate hashes match;
976 prior frozen files unchanged. Readonly mainV8 schema/revision/counts match D05-07A,
no row content read. No SQL/dependency/runner/user-file changes or external publication.

Cycle complete. [Usage and limits](docx-visible-outline.md) distinguish the supported source
subset from full Word support: inherited/style-linked/letter/picture numbering and other
unproved active semantics remain gates, and no native Word layout parity is claimed. Next
**D03-17A2b7B** integrates v3 review, storage, fixture/native checks, hides and explicit desktop
mode in one bounded vertical cycle. Real weights/GUI/native Windows/release remain separate.
