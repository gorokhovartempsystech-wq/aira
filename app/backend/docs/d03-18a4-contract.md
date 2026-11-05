# D03-18A4 — review presentation client

5 November 2026. Baseline a00af86, full 6952 passed. Allowed new client
review-transport.mjs/review-session.mjs, test_docx_client_review.py and matching ESM
acceptance scripts; this contract/result/usage and development queue. No old source,
tests, SQL, runner, dependency or server API changes.

Pinned document HTTP adapter: only review/preferences GET and explicit preference,
visibility/clear-hidden POST. Bounded 16MiB+64KiB review envelope, 64KiB commands,
30s request lifetime, no redirects/foreign origins, credentials retained in closure.

Client loads a specific successful run (or latest on explicit recovery), verifies
response/source/run/document binding, preserves fixture marker and distinguishes
no-findings from filtered/hidden empty list. Highlights require both server saved
freshness and current editor RAM hash; no quote search/reanchoring. Detached state.

Filter/question visibility and hide/unhide/clear are server commands with revision
and UUID. Lost ACK retains exact serialized request. A confirmed command is not
repeated if subsequent refresh fails. Known preference conflict requires explicit
refresh; no silent overwrite. Dispose ignores late responses. Callbacks isolated.

Pure cases cover stale RAM, foreign/mismatched results, empty states, exact lost-ACK
retry, conflict, confirmed-command refresh failure, disposal. Owned macOS/Node Fetch
proves actual analysis -> load -> hide/show -> filter -> clear and unchanged document
bytes, plus stale highlighting after edit. Fixture remains explicitly labelled.
Full scripts/check.sh required, no claim of final UI/real-model or native Windows.
