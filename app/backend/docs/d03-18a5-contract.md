# D03-18A5 — document workspace and safe tab lifecycle

5 November 2026. Baseline 2857bc6, full 6966 passed. Allowed new client
workspace-transport.mjs/document-workspace.mjs, test_docx_client_workspace.py and
matching ESM scripts; this contract/result/usage and development queue. No old
source/tests, SQL, dependencies, runner or product API changes.

One workspace owns one tab per document, focus and one global opening lane.
Explicit trusted host composition creates existing editor/analysis/review clients.
Opening reads recovery: current only for absent/empty, working/pending requires
explicit recover choice. Unknown open ACK retains exact request/key. Pending save
recovery requires explicit reconcile; retain identity after uncertain outcome.
No automatic discard, new UUID after loss or assumed clean editor.

Close refuses unresolved editor/analysis/review operations. First acknowledge
checkpoint, then stop local timers and request default checkpoint-close. Lost close
ACK keeps exact request; 410 alone is insufficient: fresh recovery must prove exact
working bytes or saved current bytes before dropping the tab. No release_local
fallback. Failed close retains state and access to last metadata. Guard exposed
client operations during close; focus switches never destroy actors. closeAll is
awaited explicitly; browser unload alone is not a durability guarantee.

Transport pins host/capability and exact canonical document/session routes, no
redirects/foreign/query paths. JSON metadata/projection bounded, 30s deadline.
Pure tests: duplicate open/focus, explicit recovery, exact retries, pending reconcile,
checkpoint failure, 410 without proof, wrong document, busy close. Native Node Fetch
through owned licensed runtime: two documents, edits, lost open/close ACK, close,
reopen/recover and host restart. Existing tests unchanged; full gate required.

## Narrow integration correction: Word source restoration

The full gate exposed a distinct 12s analysis-wait failure in the unchanged six-Word
scenario, not the earlier review HTTP timeout. Inspection found restore_source
rebuilding the same Word source twice and prepare_attempt rebuilding it three times.
This cycle additionally permits storage_codec/_records.py and the new
 test_docx_word_restore_work.py. Keep capture_source/public detached review validation
unchanged. Only freshly rebuilt, manifest-compared WordSnapshot inside restore_source
may use private from_verified after explicit shape/provenance/limit validation.
prepare_attempt may continue that same local proof. No persistent cache, no relaxed
source/manifest/command/request checks, and no test timeout changes. Add a deterministic
single-rebuild regression and retain all existing corruption/limit tests.
