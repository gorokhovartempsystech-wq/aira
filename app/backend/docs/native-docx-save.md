# Real DOCX file saving (D03-19A)

Python backend hosts can now use the [D03-19C native adapter](d03-19c-native-files.md)
and durable PostgreSQL coordinator without Node. This page describes the earlier
optional Node host integration, not a selected desktop framework.

The Node desktop host imports `createNativeDocxFiles` from
`ara/desktop/client/native-docx-file.mjs` and `createNativeDocxSave` from
`native-docx-save.mjs`. The browser renderer must not receive unrestricted paths or
filesystem access. No HTTP route accepts a destination path. No new dependency.

```js
const files = createNativeDocxFiles();
// After an explicit native Open selection:
const opened = await files.selected(absolutePath);
const doc = await importer.importDocx(title, opened.bytes);
await workspace.open(doc.document_id);
const save = createNativeDocxSave({
  exporter: workspace.client(doc.document_id).files,
  files,
  binding: opened.binding,
  pickSavePath: async () => nativeSaveDialog(), // absolute .docx path or null
});
await save.save(); // original path; only if original still matches
await save.saveAs(); // asks for a NEW path; never overwrites an existing file
```

For a new document omit `binding`. `files.selected` returns exactly the bytes whose
fingerprint is retained in an opaque, in-memory capability. Do not re-read a file
separately for import: the captured snapshot must match what was imported.
Capabilities cannot be reconstructed from JSON or supplied by an untrusted renderer.

The exporter first confirms internal save and downloads that exact revision. The
coordinator copies those bytes and keeps them after write failure. `retry()` repeats
that payload; `retryAs()` allows an explicit new destination without rerunning the
editor save. If export itself is unresolved, the next save reconciles exporter.retry.
Cancelling a picker does not discard pending bytes. Only confirmed file publication
returns a receipt. `status().saved` is the last written hash/revision, NOT proof that
the current editor is clean: compare with its revision after subsequent edits.
The host must retain the coordinator while a write is pending.

Errors are safe codes: file_changed, file_missing, file_exists, unsafe_file,
invalid_export, invalid_path, invalid_binding, file_io_error, write_uncertain, busy.
After a changed/missing source, offer Save As; never silently refresh the binding to
approve overwrite. After write_uncertain, the target may contain the export: retain
pending bytes and offer inspection/Save As, not a false success. Original mode bits
are retained on replacement; new files are private. ACLs, ownership, extended
attributes and resource forks are not promised by this adapter.

A same-directory exclusive temp file is flushed before rename; new destination uses
an atomic hard link that cannot replace an existing name. Temp cleanup is attempted
on all exits. POSIX directory fsync follows publication; on Windows there is no
portable directory fsync. Unsupported filesystem hardlinks fail safely. File stamps
include identity, size, timestamps and content hash. Symlinks, nonregular files and
hardlinked sources are rejected. Same-adapter writes are serialized.

Boundary: common portable filesystems do not offer compare-and-replace. An external
noncooperating writer can modify/replace the target between the last check and rename.
This is detection of observed external changes, not an exclusive lock against Word.
A hostile concurrently renamed ancestor is also outside this host adapter's threat
model. Post-write readback detects observed changes but cannot undo them safely.

Final native picker/IPC wiring, persistent association across app restarts, rename,
external-conflict UI and native Windows acceptance remain separate work. This module
does not claim the final app Save button is wired. No automatic writes to the user's
file from the two-minute recovery timer. No manual history/recents/ML changes.

## Shell decision (5 November 2026)

Nikita confirmed that the team has NOT selected a desktop shell yet. The filesystem
implementation here is a **Node-host adapter**, not a framework-neutral production
entry point. It is not installed as a new background service or connected to the
browser renderer. Do not infer Electron selection or Node distribution from it.
A Tauri/Python shell needs a native implementation of the same write/receipt semantics
and an explicitly scoped IPC binding; do not expose paths via the existing public
local HTTP API just to reuse this adapter. Selection of packaging/runtime belongs to
the desktop integration decision. No app UI is claimed complete by these tests.
