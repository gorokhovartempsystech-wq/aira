# D03-19B — backend file association and durable save intent

5 November 2026. Explicit continuation; independent of desktop shell.
Add PostgreSQL migration 0014, document-scoped state/service, additive tests.
Existing local desktop V13 remains pinned until a separate upgrade integration cycle.
No new HTTP path-taking routes, no filesystem IO inside SQL transactions.

State stores confirmed file binding separately from a pending exact exported payload.
Prepare locks scoped document, verifies saved bytes/hash/revision, checks association
version and commits intent before caller writes disk. Replay retains identical bytes.
Confirm requires matching observed digest and records actual file identity. Abort
requires proof target is still old/absent; uncertain or conflicting files keep intent.
Restart can read intent and classify intended-content/old-state/conflict. No silent
refresh of original binding; Save As only changes binding after confirmation.
Dirty status compares confirmed file hash with explicit current-content hash; no
inference from internal checkpoint cleanliness. Paths and bytes never in repr/logs.

Migration must preserve existing data and reject nonempty downgrade. Historical
schema tests must compare their pinned model subset, retaining all old checks;
head schema tests compare full metadata. No runner or main database migration.
