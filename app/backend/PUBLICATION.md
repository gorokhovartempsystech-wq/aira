# AIRA backend checkpoint — 5 November 2026

Source local commit: 456c7043a5b1564c508ae647fbe72920b4ae3096. Code/tests/migrations are byte-identical to this snapshot.
Documentation copies omit internal links and personal machine paths. Local archives, databases,
secrets, runtime binaries and uncommitted research/presentation artifacts are excluded.

## Current state

Local DOCX editor/storage, license server/client, owned macOS runtime, fixture analysis,
review/filter/hide backend and client command/autosave/HTTP modules are included.
Real model package and final frontend integration are still pending. This is not a release.

A1 full gate:6897 passed,45 skipped,24 subtests. Latest A2 targeted regression:196 passed,
including37 new cases. Two full A2 attempts hit an existing Word review ReadTimeout after
retry; isolated repetition passed, but full acceptance remains OPEN. No checks were weakened.
See docs/d03-18a2-result.md and docs/development-queue.md for the stopping point and next work.

## Start here

- docs/current-product-scope.md
- docs/desktop-composition.md and docs/desktop-build.md
- docs/docx-client-session.md and docs/docx-client-transport.md
- docs/docx-editor-api.md and docs/docx-review-api.md

Run repository commands from app/backend. Prepare dependencies using scripts/bootstrap.sh;
full checks require the local PostgreSQL setup in docs/local-postgres.md. No automatic
migration of an existing user database is authorized by this snapshot. The copied Ralph
harness uses standalone-project assumptions; monorepo Git-root adaptation is not verified.
The team's existing engine and frontend remain separate; this upload does not claim their integration.
