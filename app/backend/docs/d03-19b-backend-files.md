# Backend file saving state (D03-19B)

The [D03-19C Python native adapter](d03-19c-native-files.md) now implements this
protocol; no GUI framework is needed to exercise real-file save/recovery.

Trusted Python host API, not an HTTP route. No shell framework, Node runtime or
model package is required. Requires schema `0014_docx_file_states`. Constructors
and imports do not open DB/files or load settings. Use an explicit DocumentRuntime.

1. Import exact bytes with the normal DOCX service. `storage.attach(runtime, id,
   Observation(path=..., identity=..., sha256=...))` records the initial selected
   source only if it matches current persisted DOCX. No automatic rebinding.
2. After confirmed editor save, `storage.prepare(... operation_id=UUID,
   expected_version=..., storage_revision=..., source_sha256=..., save_as=None)`
   commits a pending exact payload. `save_as` selects a new path and requires
   absence; it does not silently approve overwriting an existing destination.
3. `coordinator.resume(runtime, id, files=adapter)` observes the target. If bytes
   already match intended content, confirms the operation without rewriting. If
   unchanged/absent as expected, writes and verifies. If conflicting, refuses and
   retains the intent and old association. Native IO happens outside SQL transaction.
4. `storage.read` after restart returns pending payload and binding. `finish`
   confirms a readback, including a lost-ACK replay. `abort` only clears intent
   after host has stopped its writer AND proved the old/absent state unchanged.
   Read failure is NOT proof of absence. Never cancel a concurrently running writer.

Adapters implement observe(path)->Observation|None and write(path, bytes, expected).
Identity includes the file's native identity and relevant timestamps; observe must
hash the exact bytes consistently. write enforces expected fingerprint/absence and
atomic publication. The host must own the application's existing single-owner data
home. A process lock serializes coordinator operations within that owner; this is
not a distributed filesystem locking protocol.

`Snapshot.dirty_for_file(current_sha256)` compares actual content hashes, not internal
DB/checkpoint dirty flags. Host must obtain hash of current edited content: a hash of
an earlier internally saved revision cannot prove current unsaved edits are clean.
Pending and confirmed file revision remain separate from later editor changes.

No content or path in record repr; DB errors use existing sanitized boundary. Pending
payload is bounded 32MiB and survives unrelated later document saves. Paths are private
local metadata, not displayed in logs and not uploaded.

Compatibility: the legacy desktop default remains V13. The explicit
[D03-19D V14 profile](d03-19d-desktop-files.md) now installs/verifies V14 and upgrades
V13 with the existing owned backup/recovery machinery. Unknown future targets remain
rejected. Historical V13 checks still compare its exact table inventory. Existing
analysis/review services admit additive V14 alongside their prior versions.
