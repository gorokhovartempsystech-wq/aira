# D03-17A2b6c2 — native structured fixture runtime

5 November 2026. Baseline `f7dedca`, frozen contract/acceptance `8a7040b`.
Initial red:16 failed,1 passed,10 errors /11.28s. Ten errors came from new edge-test
preparation: the separate tests directory did not expose the shared disposable PostgreSQL
fixtures. Added only three fixture imports under the contract's preparation-only exception;
all frozen function/assertion ASTs unchanged. Corrected red:26 failed,1 passed /3.30s.
First implementation:27 passed /14.92s. Seven-file lifecycle/source/fixture regression:
167 passed,2 warnings /26.53s. No old test changed.

The explicit structured supervisor fixes source admission to direct-lists, native mode review2
and distinct fixture2 provenance. It executes and restores structured results on real macOS
child processes; immediate Stop preserves the accepted source without publishing a result.
Restart/new run and retries of both legacy and structured parents preserve original source,
revision, profile and manifest even after a new current document is saved. Idempotent replay
precedes provider/config validation. Unsupported/empty/scoped/corrupt inputs fail atomically.

Exactly seven old hooks: common admission/retry extraction, private fixed source-policy
selection, and the two native child dispatches/mode sets. Both public signatures and
saved-start/retry algorithm ASTs match the baseline after the single fixed builder/loader
substitution respectively. Original public defaults,
ownership, transport, guardian, publication/drain algorithms, SQL and migrations unchanged.
No main database migration. Native Windows child-body protocol tests are portable checks,
not native Windows acceptance. Fixture2 is synthetic and does not run a real model.

`bash scripts/check.sh`: **6321 passed,45 skipped,79 warnings,24 subtests passed /804.76s**,
exit0; Ruff884 files. Pre/post958 frozen hashes match;946 prior files outside seven hooks
unchanged. Readonly mainV8 schema/revision/counts match C1; no row content read. Cycle complete.
Structured presentation/correspondence and desktop integration follow separately; real ML and
native Windows/Word/release gates remain open.
