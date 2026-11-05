# D03-18A3 — saved-version analysis client completed

5 November 2026, baseline 0be6db7. New inert ESM coordinator and pinned HTTP adapter.
Save acknowledgement supplies the exact source/revision and command identity. Lost
admission reply retains the original serialized request/key; explicit retry does not
save again. Automatic receipt polling, independent Stop, old-source retry and disposal
are implemented. Backend is authoritative for terminal state and five-minute timeout.

Initial red: 9 failed due to missing module. First pure pass: 9 passed. Actual owned
macOS/Node Fetch integration plus initial pure cases: 10 passed, 2 warnings, 24.92s.
Ordinary and merged-table files were edited, saved, checked by the explicit fixture,
replayed after a lost admission ACK, retried and stopped with an actual terminal
cancelled/succeeded outcome. Other DOCX package parts retained exact original bytes.
Final pure edge suite: 13 passed (source mismatch, poll failure/replay, callback/timer
failure and late Stop added). Old actor/transport and all existing tests unchanged.

Mixed client regression under sandbox: 48 passed, one old real-redirect test failed
because listen(127.0.0.1) returned EPERM. The full gate uses normal approved local
process/network access and includes that unchanged test; do not treat EPERM as a
code regression or hide it by skipping/relaxing the test.

Ruff check and format passed. Full scripts/check.sh passed: **6952 passed, 45 skipped, 78 warnings,
24 subtests, 1314.50s, exit 0**. The unchanged real-redirect test passed here.
Read-only main schema/count snapshot matches the previous baseline. Acceptance closed. See docx-client-analysis.md for usage. Results, stale RAM binding, tabs,
open/recovery and confirmed-version export remain subsequent cycles. No real-model,
final-frontend, Windows-native or release-readiness claim.
