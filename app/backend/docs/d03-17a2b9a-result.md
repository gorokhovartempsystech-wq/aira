# D03-17A2b9A — ordinary Word package reading complete

5 November 2026. Baseline `cf485fd`, acceptance freeze `f4cdb35`.
Red: **56 failed,6 passed /3.31s**. First implementation target: **6 failed,56 passed
/45.18s**; the six failures came from the new canonical-comparison preparation helper
passing a dataclass/UUID to a dictionary JSON helper. The local wrapper now uses the existing
payload encoder; all24 frozen function bodies and assertions remain unchanged. This is the
preparation-only correction allowed by the contract. Corrected target62 passed. Fifteen
review cases were appended. The last one first failed and caught an unknown package-root
image role being classified as unused media; source role validation now rejects it.

Final new target **77 passed /51.93s**; prior reader/integration regression **311 passed
/8.07s**. Six independently produced synthetic default-template DOCX files read and map
every literal fragment to original XML while retaining numbering/notes provenance. The new
fixed profile proves auxiliary role closure and selected numbering without rewriting the ZIP.
Old profiles and seven captured style-list outputs remain unchanged. The old private shape
validator only gained fixed optional policy defaults; the previous public defaults are intact.

`bash scripts/check.sh`: **6774 passed,45 skipped,79 warnings,24 subtests passed /932.15s**,
exit0. Recursive Ruff942 files plus explicit builder check/format5 passed. All1041 gate hashes
match; all1020 prior files outside the one permitted private shape hook remained unchanged.
Readonly mainV8 schema/revision/counts match B8B; no row content was read. Native Windows gates
remain skipped explicitly. No publication or unrelated user-file changes.

Cycle complete. [Usage and precise limits](docx-visible-word.md). This is source reading and
mapping, not yet a desktop integration, complete Word feature matrix or native layout claim.
Next D03-17A2b9B integrates the fixed profile through persistence, fixture review, native
supervision, hides and owned macOS HTTP. Afterwards prioritize the missing DOCX autosave
coordination; the old generic workspace autosave is not connected to the DOCX editor.
Real ML package, final GUI, native Word/Windows and signed release remain separate gates.
