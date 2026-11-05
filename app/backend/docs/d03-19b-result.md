# D03-19B — persistent file association and recovery state

5 November 2026, baseline 55276ab. Backend implementation, no shell selection.

Added V14 table with scoped document FK, bounded private state and exact pending
DOCX payload. Explicit attach/prepare/read/finish/abort, revision CAS and operation
replay. Confirmed file observation/revision remain separate from pending save and
later editor changes. Current-content hash determines file dirtiness.

A shell-neutral coordinator performs observation/writing outside SQL transactions.
After restart intended bytes already present => confirm without rewriting; unchanged
old state => write and verify; conflicting contents/read error => keep pending intent.
Adapter must enforce expected old fingerprint/absence and host must own data-home.
No new HTTP endpoints, untrusted file paths or Node dependency in this service.

Verification: 17 new PostgreSQL/state tests pass (including a real reader subprocess,
concurrent prepare, lost ACK, before/after-publication fault adapters and nonempty
migration downgrade refusal). Combined new/schema/review compatibility checks:65 pass.
Native first-schema/upgrade compatibility:26 pass. Full `bash scripts/check.sh`: **7042 passed,45 skipped,77 warnings,24 subtests**,
1308.13s,exit0; log `.runtime/d03-19b-full2.log`.

Initial full gate exposed historical desktop V13 target assumptions, not a need to
choose GUI. Preserved explicit V13 launch/upgrade and exact historical inventory,
excluding only V14's new table from its expected model. Known bundled V14 migration
head can coexist with explicit V13 installation; arbitrary unknown heads still fail.
Historical V13 schema test compares the complete V13 model subset; none of its old
checks removed. Head-schema tests compare all ORM metadata including the new table.
Existing analysis/review services admit additive V14 alongside their prior revisions.

Limits: production launcher remains V13 until a separate backup/upgrade integration
cycle. Backend service is available on V14, not silently enabled in running desktop.
Recovery tests in this cycle inject the filesystem adapter; D03-19C follows with
real Python native IO. Final picker/IPC, Windows-native acceptance, manual history,
recents and model-context extensions are not claimed completed.
