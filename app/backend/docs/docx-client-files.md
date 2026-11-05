# DOCX file client integration

`createConnectedImporter({origin, sessionToken, onState?})` creates an inert client
for a trusted live licensed localhost connection. `create(title)` uses the AIRA
blank template; `importDocx(title, Uint8Array)` uploads exact DOCX bytes. Both return
confirmed metadata. Only then call `workspace.open(metadata.document_id)`. Import
has no authority to replace/focus a tab itself. `status().pending` means the exact
UUID/title/bytes are retained; `retry()` repeats that intent, never allocates a new
UUID. The input is copied, including Node Buffer views. Definite initial 413/415/422
refusals allow corrected input; unknown outcomes remain pending.

`createConnectedWorkspace` exposes `workspace.client(id).files.exportDocx()`.
It saves the actor and obtains that exact saved target. On uncertainty, expose
`files.retry()`; editor writes, checkpoint, new analysis admission and tab close are
blocked while export is pending. Download may be cancelled with `files.cancel()`;
uncertain save must first be reconciled through retry. Cancellation never discards
an editor request or reverses an acknowledged save.

The result contains `filename` (canonical document UUID + `.docx`), `bytes`,
`sha256`, and `storageRevision`. Pass bytes to the native save picker or explicit
browser download. Choosing a destination and confirming an OS file write belongs
to the shell: obtaining bytes is not proof that the user's chosen file was written.
No arbitrary path or remote URL is accepted here. The editor's save receipt is used
for `saved-content`; no fallback to the potentially newer `/content` route.

Transport: exact localhost/capability routes; POST only, no redirects or credentials,
30s deadline, 32MiB binary/64KiB JSON limits. Binary replies require DOCX MIME,
`saved` copy-kind, revision and ETag matching SHA256 of downloaded bytes. The exporter
also matches hash/revision to the acknowledged editor save. JSON metadata numeric
revisions must be safe integers; imprecise values are rejected rather than rounded.

These modules implement file coordination, not the final UI, native file picker or
visual Word layout acceptance. No PDF/OCR or automatic AI edits. Working/recovery
rescue downloads already available on the backend are not wired as silent export
fallbacks. Real ML, Windows-native and release verification remain separate.
