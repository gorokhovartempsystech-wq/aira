# D03-17A2b6a — structured review v2

5 November 2026. Baseline `eaa1ef5`, frozen contract/acceptance `d2ef73c`.
Red **30 failed /0.54s**. First implementation29 passed/1 failure: the new positive
related-evidence fixture incorrectly used type=formulation and omitted status=active.
Corrected only its preparation to type=contradiction/status=active under the contract's
explicit correction allowance; all frozen assertion ASTs unchanged. Corrected acceptance
**30 passed /0.68s**. Review added5 cases for syntactically valid unknown/prefix/wrong
related spans, invalid source DTOs and unchanged/resolvable closed schema definitions:
**35 passed /0.74s**. Old tests unchanged. Regression7 files **195 passed /13.48s**, including native fixture lifecycle on disposable PostgreSQL. Initial sandbox-only regression encountered local DB access errors; rerun with normal reviewed local-process access passed.

New protocol carries exact source-derived list labels and note references in the engine
payload and result while preserving literal fragments/offsets/source slices. Rehashed
context or swapped PreparedReview bytes/hash cannot authorize publication. Source is
rebuilt once per call, including zero/many findings; exact byte bounds include context.
Old v1 profiles and APIs remain closed. Only old hook extracts the existing private
validation algorithm with call-time pinned mapper/request/base factories. An AST comparison with the baseline confirmed the original validator body is exactly unchanged after substituting the three private function names. No global profile registry, storage/worker/runtime/SQL/dependency changes or actual inference.

New self-contained v2 schema uses unchanged common v1 definitions and closed added DTOs.
External jsonschema is unavailable in project, host and bundled Python: optional full
meta-schema validation was not run and no dependency installed. Structural/ref/common
schema assertions and actual wire/source validation passed; these are distinct checks.

944 frozen hashes and936 old files outside the one hook verified before full gate.
`bash scripts/check.sh`: **6188 passed, 45 skipped, 79 warnings, 24 subtests passed /798.77s**, exit0; Ruff873 files. Post-gate944 hashes match;936 previous files outside the one hook unchanged. Readonly mainV8 schema/revision/counts match E2. Cycle complete. Storage/runtime integration, actual model, native Windows/Word and release gates remain separate work.
