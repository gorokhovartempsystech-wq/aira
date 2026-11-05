# D03-18A3 — saved-version analysis client

5 November 2026, baseline 0be6db7; prior full gate 6938 passed. One cycle covers
save/check/poll/stop/retry through the existing licensed loopback API. No ML/UI claim.
Allowed: new desktop/client/analysis-transport.mjs and analysis-session.mjs; new
acceptance test_docx_client_analysis.py and docx_client_analysis_*.mjs; this contract,
result, usage and development queue docs; ignored diagnostics. No old tests, actor,
SQL, dependencies, runner, public routes or product scope changes.

Transport pins trusted loopback origin/capability/document, preserves serialized
JSON, uses 30s bounded Fetch (64KiB metadata), refuses redirects/foreign paths,
keeps an independent Stop lane. No constructor I/O. Only analysis admission,
request metadata, stop and old-run retry paths. No result download in this cycle.

Coordinator owns save-before-check, exact pending admission key/body, explicit
retries after unknown outcome, polling, independent stop and disposal. Never submit
before acknowledged save; retry uncertain save through the existing editor actor.
Validate receipt identity/source before exposing state. Stop intent is not cancelled;
a committed success may win. Terminal state cannot regress under late replies.
Backend owns five-minute deadline; client network timeout is not analysis timeout.
Old-run retry preserves source; new check saves current text. Errors/callbacks do not
expose capabilities or cause extra writes. Constructor inert, timers cleared on close.
UI must route editor commands through its single actor and honor busy/save admission
state; no second actor or hidden auto-fix is introduced.

Acceptance: pure ESM save failure/lost admission response/exact retry/double click,
foreign receipts/source mismatch, stop/poll race, terminal monotonicity, close late
response, callback/timer failures and independent transport lanes. Actual Node Fetch
against owned macOS fixture runtime proves edited saved source, metadata completion,
replay and old-run retry. Old tests unchanged; full scripts/check.sh required.
