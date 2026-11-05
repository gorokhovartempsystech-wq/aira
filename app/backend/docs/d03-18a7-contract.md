# D03-18A7 — reproducible whole DOCX workflow and handoff

5 November 2026. Baseline4282fbc, full7005 passed. Final independent integration
cycle for F03–F12; no new product features. Allowed new test_docx_client_workflow.py,
docx_client_workflow_owned.mjs, scripts/check_docx_workflow.sh, this contract/result,
docx-workflow-handoff.md and development queue. Old source/tests/contracts, SQL,
runner and dependencies unchanged. Any discovered source defect needs a concrete
narrow correction recorded before editing; do not widen the product scope.

One production-client workflow through owned macOS licensed fixture runtime:
create a template and import plain/merged-table DOCX; edit/undo/redo, switch tabs;
advance only the client 120000ms autosave scheduler, with actual HTTP checkpoint;
analyse/save, hide/filter, edit to stale; close and restart host; fresh licence check,
explicit draft recovery and persisted hides; fresh analysis/results/manual correction;
confirmed saved export; reimport and reopen those bytes. Verify exact prefixes,
untouched auxiliary package parts, saved hash, fixture labels and closed resources.
No arbitrary sleep replacing backend completion, no user archive or external model.

Single command runs the new scenario and optionally emits synthetic DOCX/report
artifacts under an isolated generated .runtime directory. Existing full gate remains
mandatory. Record main schema/count equality. Document shell integration entrypoints,
real-model/UI/native-Windows/visual-Word/public-TLS/signing limitations. Synthetic
licence transport is not a deployed licensing service. This is a working client/backend
scenario, not a final end-user GUI or acceptance of Word visual compatibility.

## Required integration correction: shared host request lane

The new whole-workflow test failed after all three 120000ms timers fired together:
one actor checkpointed, two retained uncertain requests. Reproduction confirmed the
server's existing EditorTransport semaphore(1) and ordinary host semaphore(2):
per-tab client lanes alone cannot coordinate the common server capacity. This is
not a reason to raise limits/timeouts or retry blindly. Narrow additional paths:
new client/request-queue.mjs, document-workspace.mjs composition, new
 test_docx_client_request_queue.py/docx_client_request_queue_cases.mjs. Serialize
ordinary workspace/editor/analysis/review/export transport dispatches through one
bounded FIFO (128 in-flight/queued); release on success/failure. Preserve exact
requests and explicit uncertainty. Analysis Stop bypasses this lane through its
existing separate transport lane. No backend change and no old-test changes.
The simultaneous real-HTTP autosave acceptance stays unchanged.
