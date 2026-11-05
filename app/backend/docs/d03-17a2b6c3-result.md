# D03-17A2b6c3 — structured review presentation

5 November 2026. Baseline `7d13970`, frozen contract/acceptance `8774bfb`.
Red:14 failed,7 passed /2.12s. First implementation:21 passed /2.17s. Frozen tests
unchanged; no preparation correction. Regression across five old presentation/structured
codec/HTTP/native files:96 passed,3 warnings /18.63s. Ten additional baseline-source
probes confirmed byte-identical legacy views, view hashes and dismissal keys across empty
results, default display, hiding, restoring, filtering and question suppression.

Two added lines in the single old source hook select view2 for a source-verified review2
and retain its complete document_context. Legacy view1 bytes remain unchanged. Filtering
never trims source context, creates literal slices for generated labels, changes the stored
result or turns fixture/filter-empty output into a real no-findings assertion. Corrupt or
rehashed context is rejected even with all findings hidden; context counts toward MAX_VIEW.

The new standalone closed view2 JSON Schema has17 required fields and28 local references;
source/evidence/provenance/context definitions match review2 exactly. Shape/reference checks
ran; optional external metaschema validation did not run (jsonschema/fastjsonschema unavailable,
no dependencies installed). Source authenticity and cross-field correctness remain behavioral
storage-codec checks, not claims supplied by the shape schema.

`bash scripts/check.sh`: **6342 passed,45 skipped,82 warnings,24 subtests passed /804.98s**,
exit0; Ruff885 files. Pre/post961 hashes match;957 prior files outside one hook unchanged.
Readonly mainV8 schema/revision/counts match C2; no row content read. Cycle complete.
Structured correspondence/resolution and HTTP/desktop integration follow; real ML/native
Windows/Word/UI/release gates remain separate.
