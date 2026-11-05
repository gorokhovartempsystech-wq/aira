# D03-19A — native file adapter and save coordinator

5 November 2026; baseline dd17b01. F11/F12, explicit real-file saving request.

Implemented a trusted Node-host adapter and per-document coordinator. Imported file
bytes and original fingerprint come from one read. Confirmed exports are copied,
size/hash/revision validated and written via a flushed same-directory temporary file.
Original saves compare identity/metadata/hash before replacement; new paths use
no-replace publication. Symlinks, nonregular/hardlinked sources, changed/missing
originals and existing Save As targets are refused. Original POSIX mode bits retained.

File receipt is distinct from internal editor save. Cancelled picker is not success;
failed writes retain exact bytes for retry/Save As. Unresolved export uses the existing
exporter's retry rather than silently creating another save. Published but unconfirmed
write returns write_uncertain; no false successful-file status.

## Verification

- 16 new real-filesystem/state tests passed, including injected disk/flush/rename
  faults, observed external change immediately before publication, missing source,
  unsafe links, duplicate requests, cancellation and copied-payload retry.
- Additional manual native probe used all three synthetic workflow DOCX artifacts
  (new/plain/table): create, reopen, replacement and byte identity passed.
- Lost export acknowledgement → exporter retry → actual DOCX write passed.
- Full `bash scripts/check.sh`: **7025 passed, 45 skipped, 81 warnings,
  24 subtests passed**, 1344.05s, exit 0. Log:
  `.runtime/d03-19a-full-native-clean.log`. Ruff lint/format passed.

First sandbox full-gate attempt was interrupted after permissions blocked local DB
connections. It left 30 unattached shared-memory segments from this run's terminated
initdb children, exhausting macOS SHMMNI. Elevated gate then failed cluster startup.
A direct synthetic initdb probe confirmed SHMMNI exhaustion. Only those 30 segments
were removed after owner/size/zero-attachments/dead-creator checks. Active development
DB and older segment were not touched. The isolated cluster test then passed; full
gate was restarted. No code/tests were weakened to mask this environment failure.

## Limits and next step

This is not a finished Save button or a selected desktop architecture. Nikita confirmed
that the shell is not selected. The adapter requires a Node host; no Node runtime was
added to the installer, no path-taking HTTP route was exposed and no final UI changed.
The shell must retain pending coordinator state and compare the saved receipt with
current edits. There is no persistent file binding across restarts yet.

Portable rename does not provide compare-and-replace against a noncooperating external
writer after the final fingerprint check. Windows native acceptance, ACL/xattr
preservation and arbitrary simultaneous external changes are not claimed. Save As
currently supports a new path only, never an implicit overwrite of an existing file.

[D03-19B design](d03-19b-file-association-design.md) records durable association/crash
intent requirements. It is not implementation or a completed cycle. Native shell/IPC
selection is required before wiring association persistence to the production writer;
manual version history, recent documents and AI context were not added by inference.
See [host integration contract](native-docx-save.md).
