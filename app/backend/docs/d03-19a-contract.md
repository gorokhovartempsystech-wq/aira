# D03-19A — native DOCX file persistence

5 November 2026 — implementation on explicit user request.
Scope: F11/F12, explicit user request to save real files. New host-only Node ESM
adapter and save coordinator in desktop/client, additive acceptance tests and docs.
No SQL/API/runner/dependency or old-test changes. No model/UI redesign.

The trusted shell supplies a native picker; paths never come from HTTP/model text.
Read an existing selected file once to capture bytes and identity for import. Save
an acknowledged exporter result only, verify size/digest/revision, copy input.
Use same-directory exclusive temporary file, flush, then atomic publication.
New file publication must not overwrite a file appearing after selection.
Existing saves require unchanged identity, metadata and content before publication;
reject symlinks, non-regular files and hardlinked files. Missing/changed destination
requires explicit user choice, never automatic replacement or retry against new data.
Same adapter serializes writes; external noncooperating writers can race the final
check/rename (no portable atomic compare-and-replace). Document this limitation.

Coordinator separates internal export from OS save. Cancel picker is not success;
failed writing retains exact copied export for retry/Save As, never triggers another
editor save silently. Success identifies saved revision/hash, not current editor
cleanliness. Original-file binding changes only after verified write. Errors expose
safe codes, not paths/content. No background autosave to source. Source-file metadata
persistence across launches and final native picker UI remain separate integration.

Acceptance: real temporary filesystem, create/replace/read, external modification,
missing file, symlink/hardlink, invalid payload, cancellation, concurrent requests,
write/flush/publication faults and exact retry. Full scripts/check.sh required.
