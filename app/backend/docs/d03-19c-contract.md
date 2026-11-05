# D03-19C — Python native writer for the backend coordinator

Planned next bounded cycle. Use current Python host runtime and D03-19B adapter
protocol, no Electron/Tauri assumption and no Node dependency. New module in
ara/docx_files, additive real-filesystem tests; no schema/API/runner changes.

Read absolute selected .docx paths with bounded bytes and stable before/after stat,
return canonical path, identity stamp and digest. Reject symlink/nonregular/hardlinked
sources. Write validated immutable bytes to private exclusive same-directory temp,
fsync, recheck expected old observation or confirmed absence, atomically publish,
verify final bytes. Preserve existing POSIX mode, private new files; cleanup own temp.
Never log paths/content. Errors after publication remain uncertain and recover via
B coordinator. Missing file distinct from permission/read failure. No locks against
noncooperating external programs are claimed by portable compare/rename.

Acceptance: new file/original replacement, external modification/deletion, concurrent
file creation at new destination, write failure, real restart with PostgreSQL pending
intent, hash mismatch, read failures, and save-reopen of synthetic DOCX. Full gate.

Allowed related changes: sanitize native exception chaining at storage boundary;
explicit version-guarded retarget of retained pending bytes for Save As after a
conflict (old writer must be stopped first). No automatic overwrite approval.
