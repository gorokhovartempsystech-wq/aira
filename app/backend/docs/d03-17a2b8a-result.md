# D03-17A2b8A — paragraph-style numbering source reader complete

5 November 2026. Baseline `8952b63`, acceptance freeze `a898687`. Seven positive selected
source/context fixtures were preflighted before freeze. Red **49 failed /0.58s**; first
implementation **49 passed /0.52s**. Review appended ten cases, final target **59 passed /0.65s**.
An unfrozen appended relationship test initially imported a nonexistent helper; corrected that
preparation before the final run. All original frozen49 test bytes remain an exact prefix.
Source/outline regression **718 passed /11.90s** includes the new59.

The new fixed StyleListSnapshot reads direct and paragraph-style numbering using physical
style-property/selector/chain/abstract-binding anchors. Explicit/default/basedOn selection,
nearest overrides/removal, tables/wrappers, blank/hidden items, notes and field boundaries are
source-proved. It reuses all nine outline levels and four formats/counter policies. Contexts
use each styles part's actual namespace. Repeated private style choices are cached, while
output chain cost remains aggregate-bounded (the review fixture has285 raw nodes versus500
chain entries and correctly fails at400). Mapping rebuilds even an empty request batch.

`bash scripts/check.sh`: **6630 passed,45 skipped,79 warnings,24 subtests passed /848.85s**,
exit0. Recursive Ruff919 files plus explicit builder check/format5 passed. All1008 gate hashes
match; all996 prior frozen files unchanged. Readonly mainV8 schema/revision/counts match B7B,
without reading document rows. No old source/tests/schemas/SQL/runner/dependencies changed.

Cycle complete. [Usage and limits](docx-visible-style-lists.md). Style ilvl/default/table
numbering, ancestor-only fallback, style links, replacement pStyle and other unproved Word
semantics remain gates. This pure reader does not yet change app admission or stored profiles.
Next **D03-17A2b8B** integrates review4/storage/fixture/native/hides/desktop in one vertical cycle;
its source fixtures and acceptance draft are prepared. Real ML/UI/native Word/Windows/release
remain separate. No remote publication or changes to the user's unrelated files.
