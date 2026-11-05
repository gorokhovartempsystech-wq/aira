# D03-19B — file association after restart

5 November 2026. Original design followed by independent backend implementation.
See [backend contract](d03-19b-backend-files.md) and the cycle result for verification.
Desktop framework has not been selected; this does not block SQL state/recovery or
a Python host adapter. D03-19A Node adapter does not select a shell implicitly.

## Required behaviour independent of shell

Store the relationship between document UUID and the selected original file, plus
the fingerprint of the exact bytes imported or last successfully written. The
internal editor save/recovery checkpoint never refreshes this file fingerprint.
Store the last successfully written document revision separately from the current
editable revision. Dirty-for-file is not the existing internal DB dirty flag.

On restart, load this record without silently adopting current filesystem content.
Before saving again, compare the actual file to the recorded identity and digest.
If changed/missing, preserve the internal document and require explicit user choice
or Save As. Never silently select a same-named file in another directory.

Do not treat path as document identity: Save As maintains document identity and only
changes its original-file association after successful publication. Failure/cancel
must preserve the previous binding and all pending bytes. No user-facing recent list
or manual-version history follows automatically from this metadata.

## Crash boundary requiring a durable intent

Database commit and filesystem replacement are not one atomic transaction. Before
publication retain document ID, expected old fingerprint, target path, intended
hash/revision and an operation ID in a private pending record. Publish DOCX, verify,
then acknowledge association. On restart a pending record is not a success receipt:
compare target to both old fingerprint and intended hash. Exact intended bytes can
be reconciled to the recorded revision; old unchanged state permits explicit retry;
anything else is a conflict. Do not retry against newly observed external contents.

The final implementation must use the application's existing single-owner data-home
and local database, with bounded records, schema validation and migrations. Do not
create competing ad-hoc app data stores, browser localStorage or an independently
writable path API. Keep full paths and document bytes out of diagnostics.

## Integration decision still required

Choose who owns the picker, native filesystem handles and application close. Define
a trusted IPC capability for one selected file and the saved-revision receipt. With
a Node shell D03-19A is reusable; another shell needs the matching native adapter.
File association persistence must be wired to the same writer. The backend can
implement and test this protocol on the existing Python runtime before shell selection.
The final picker/IPC/UI binding remains separate; it is not a blocker for SQL recovery.

Acceptance must cover actual process restart, stale/missing/moved source, corrupt or
oversized metadata, failure before/after publication and before/after association
commit, concurrent requests, cancelled Save As, and edits newer than saved receipt.
Windows and macOS native acceptance remain separate. No tests or statuses changed.
