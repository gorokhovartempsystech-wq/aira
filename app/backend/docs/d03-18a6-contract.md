# D03-18A6 — DOCX create/import and confirmed export

5 November 2026, baseline 96bdfdb; full 6982 passed. Implements F04/F11 only.
Allowed new file-transport.mjs/docx-files.mjs, new test_docx_client_files.py and
matching ESM scripts; narrow document-workspace.mjs composition/action guards;
this contract/result/usage and development queue. Old tests, backend routes, SQL,
dependencies, runner and main DB unchanged.

Create/import retain one UUID/title/copied binary intent across unknown outcomes.
Create has an empty body and no Content-Type; import is bounded DOCX binary only.
No automatic tab replacement before acknowledgement. Validate exact document/title
metadata and safe integer revisions; never coerce imprecise JSON numbers.

Export saves current actor first, waits for a confirmed saved view, then requests
saved-content using that save receipt's UUID and resulting counters. Download must
match saved source SHA256/revision, DOCX media, copy-kind and bounded bytes. No GET
latest substitution. Unknown save uses editor.retry; unknown download repeats exact
request. Workspace blocks edits/checkpoints/new analyses/close while export is busy
or unresolved. Cancelling an uncertain save cannot discard editor pending state.
Export returns bytes plus canonical UUID filename; caller owns file picker/write.

Trusted host-only transport, no redirects/cookies/referrer, one lane, 30s deadline,
32MiB binary and 64KiB JSON bounds, strict routes. Constructors inert. Pure checks
cover input copying, exact lost-ACK retry, metadata, source/revision mismatch, bounded
media/response/deadline, save-before-export, and workspace locks. Native licensed
runtime covers create, imports, edits and exact confirmed exports; auxiliary Word
parts preserved. Full scripts/check.sh and unchanged main snapshot required.
Final GUI/native picker, visual Word, real ML and Windows/release gates remain external.
