# D03-17A2b9B — implementation checkpoint, integration gate still open

5 November 2026. Baseline `9c02800`, acceptance freeze `ba09518`.
Red **34 failed /11.27s**, including the precise additive metadata test. Initial pure target
**19 passed /134.26s**; six additional review cases **6 passed /1.16s**. First native/HTTP
set **4 failed,11 passed /210.12s**: native source-pinned checks/retries/stop worked, but the
HTTP scenario found two genuine integration dependencies, not test-preparation mistakes.

1. A valid DOCX whose body consists only of tables cannot create the current body-only editor.
   Existing legacy acceptance explicitly requires that refusal. It must remain unchanged;
   a separate opt-in table editor cycle will supply the needed path.
2. Repeated source reconstruction inside result validation made hidden-result HTTP requests
   exceed the unchanged5s client timeout. Fixed within the permitted codec/new-word-review
   paths: a private continuation uses the freshly rebuilt source only within that call.
   There is no global/persistent cache, DTO trust flag, skipped initial XML proof or change to
   public mapping behavior. All public entrypoints still verify original bytes. After this
   correction the pure target **25 passed /97.17s**, and the three failing hide/manual-edit
   HTTP cases **3 passed /103.42s**. Old four-profile result/view/key/request/reply bytes match.

Review5/view5, source codec, fixture2/native transport, generated-context budgets and owned
mode are implemented. The frozen33 new integration cases remain mandatory, with six appended
review cases. No frozen assertion changed. The full gate has NOT been run for this checkpoint;
B9B is NOT complete. Do not call the product ready or count this as a completed cycle.

Next prerequisite D03-17A2b9C1 adds explicit table-aware selection/checkpoint/edit admission,
without widening the legacy editor default or changing B9B tests. Keep this implementation
checkpoint separate from that source change; after the dependency, rerun B9B and the full
repository gate. Original DOCX and unrelated user edits remain untouched. No publication.

## Completion after the independent C1 prerequisite

The checkpoint above remains historical evidence, not the current completion status. C1 kept
all B9B assertions and supplied explicit table-aware editor admission. Frozen B9B plus metadata
**40 passed,2 warnings /292.82s**; the old codec/review regression270 passed45.79s. All four prior
profile byte probes remained exact after the private per-call proof continuation.

Shared full gate after the prerequisite: **6849 passed,45 skipped,81 warnings,24 subtests passed
/1280.48s**, exit0; recursive Ruff957 + explicit builder5,1060 immutable hashes, readonly mainV8
unchanged. C1's [result](d03-17a2b9c1-result.md) records the precise source boundary and extra
cell acceptance. B9B is now complete. Six ordinary-template files import/check/export through
the owned macOS fixture runtime, with saved manual edits, persisted hides and fresh-license
restart/retry. Real inference, final GUI, native Word/Windows and production release remain open.
