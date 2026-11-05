# Complete DOCX client/backend workflow

Run from the project root on this Mac:

```bash
bash scripts/check_docx_workflow.sh
```

This is an executable integration demonstration, not the final desktop GUI. It uses
production client modules, actual local HTTP/owned PostgreSQL and synthetic DOCX,
model responses and licence transport. No user work archive or external model is
used. The successful command prints a fresh `.runtime/aira-workflow-demo/run-*`
directory containing `new.docx`, `plain.docx`, `table.docx` and `report.json`.
Files are synthetic and safe to inspect manually; the command never chooses or
replaces a user's document. Each run has a new isolated data home and output folder.

The scenario creates an AIRA template document and imports two independent Word
fixtures (ordinary paragraphs and merged table). It edits, undoes/redoes, switches
three tabs and advances the two-minute autosave timer while performing real HTTP
checkpoints. It saves/checks, changes filters, hides a finding, edits again to mark
the result stale, closes the host and starts it again. The second host must perform
a fresh licence check. The client explicitly recovers drafts and stored hide/filter
choices, rechecks, manually edits again, exports the exact acknowledged saved bytes,
then imports and reopens each exported package. Python verifies hashes, text edits
exactly once, untouched auxiliary Word parts and closed owned resources.

The autosave clock is advanced in the test; the command does not wait two minutes
in real time. The binary exports have no AIRA findings or UI added. Reopening through
AIRA is verified; visual Word page layout and native Word automation are not.

## Requirements and safe operation

The existing project `.venv` (see `scripts/bootstrap.sh`), Node.js (PATH or the bundled
runtime) and complete project-local `.runtime/Postgres.app` 18 bundle are required.
See [local PostgreSQL setup](local-postgres.md) for the existing runtime preparation.
The demo does not install tools globally, deploy a service or migrate `ara_dev`.
It needs local process/port permissions because it runs an owned local server and
database. Windows-native acceptance remains a separate required gate.

## Frontend integration entrypoints

| Responsibility | Entry module / API |
|---|---|
| Create/import DOCX | `ara/desktop/client/docx-files.mjs`: `createConnectedImporter` |
| Open/recover/focus/close tabs | `document-workspace.mjs`: `createConnectedWorkspace` |
| Manual edits, undo/redo, autosave | `workspace.client(id).editor` |
| Save then check, poll, stop/retry | `workspace.client(id).analysis` |
| Findings, questions, filters, hides, stale state | `workspace.client(id).review` |
| Export exact confirmed saved copy | `workspace.client(id).files.exportDocx()` |

The host supplies its live localhost origin and in-memory session capability. The
renderer must not discover or persist credentials. Constructors are inert. A connected
workspace serializes ordinary host requests across tabs (bounded FIFO), including
autosave; analysis Stop uses its separate lane and bypasses that queue. After
creation/import is acknowledged, open its returned document UUID. Use the existing
editor command/projection contract for rendering and selections. Bind control state
to the clients' status callbacks; preserve pending requests and expose their explicit
retry instead of allocating a new operation. Await `workspace.closeAll()` before
shell shutdown; browser unload alone cannot prove durability. Pass exported bytes to
the native save picker and report filesystem-write success only after it completes.

See [editor analysis](docx-client-analysis.md), [review](docx-client-review.md),
[workspace](docx-client-workspace.md) and [file client](docx-client-files.md) for details.
The reproducible driver is `tests/acceptance/docx_client_workflow_owned.mjs`.

## Remaining work outside this independent integration sequence

- Anya's final renderer, native window/file-picker integration and usability testing.
- Artem's real model pack, packaged runtime integration and analysis-quality acceptance.
- Native Windows lifecycle/installer checks and visual Word compatibility on target systems.
- Public verified-TLS licensing service, production keys/policy operations and signed
  installers with actual frontend/model assets.

The demonstrated licence exchange uses a synthetic transport. Passing the workflow
is not proof of a deployed licence server, real analysis quality, final UI or full
DOCX visual compatibility. These gates are not hidden by the number of unit tests.
