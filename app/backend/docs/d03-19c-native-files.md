# Python native DOCX saving (D03-19C)

Use the existing Python backend host; no Node/Electron/Tauri choice is required.
This is a trusted host API, not a browser endpoint. Schema V14 and existing
single-owner application data-home are required for the durable coordinator.

```python
from uuid import uuid4
from ara.docx_files import storage
from ara.docx_files.native import NativeFiles, destination
from ara.docx_files.coordinator import resume

files = NativeFiles()
# Initial import: choose path explicitly in the shell, then import these exact bytes.
observed, data = files.selected(selected_path)
# doc = import_docx(runtime, document_id=..., title=..., data=data)
linked = storage.attach(runtime, doc.document_id, observed)

# After the editor's internal save has been acknowledged:
state = storage.read(runtime, doc.document_id)
intent = storage.prepare(
    runtime, doc.document_id, operation_id=uuid4(), expected_version=state.version,
    storage_revision=confirmed_revision, source_sha256=confirmed_sha256,
    # save_as=destination(chosen_new_path),  # omit to save the bound original
)
receipt = resume(runtime, doc.document_id, files=files)
```

New documents need no attach: prepare with a canonical explicit Save As destination.
`destination` resolves the parent, not a symlink to an existing destination file.
`selected` captures exact bounded bytes plus identity from a stable read. File identity
includes device/inode, size, nanosecond timestamps, mode and link count. Hardlinked,
symlink and nonregular sources are refused. Observe returns None only for absence;
permission or IO errors must not become absence.

After a crash, read the pending state and explicitly resume with `NativeFiles()`.
Do not prepare new bytes first: pending data is the exact older export the user
requested even if another internal save happened later. If content is already written,
resume confirms it without another replacement. Otherwise it requires the prior
observation/absence before publication. All native IO runs outside SQL transactions.

After a conflict, the user may choose a different new path. Stop/quiesce the previous
writer, then `storage.retarget(... expected_version=current.version,
operation_id=fresh_uuid, path=destination(chosen_path))` and resume. Retarget retains
exact pending bytes and original binding until the new file is confirmed. Lost ACK
on retarget is reconciled with read; never invent a new intent against an unknown
version. Do not call retarget/abort concurrently with a native writer.

The actual writer uses a private same-directory temp, full write + fsync, fingerprint
recheck and atomic replace (existing) / atomic no-replace link (new). POSIX directory
fsync follows publication. Windows needs native acceptance; portable Python has no
matching directory-fsync guarantee. Unsupported hardlinks fail without replacing.
Errors after publication are uncertain, never success; coordinator retains SQL intent.
Native error chains hide paths. Temp cleanup is best effort on errors/process death.

Not an exclusive lock against Word: another program can race after the last comparison
and before rename; hostile concurrent parent-directory replacement is outside this
portable adapter's guarantees. ACLs/xattrs/resource forks and power-loss behaviour
beyond the explicit fsync calls are not promised. Original ordinary POSIX mode bits
are retained; new files use 0600. Blocking operations belong on a host worker thread.

Final UI picker/IPC wiring remains separate. The [D03-19D owned V14 profile](d03-19d-desktop-files.md)
now supports native launch/upgrade and these services without choosing a UI framework. The
older Node adapter stays available, but is not required by the Python workflow.
