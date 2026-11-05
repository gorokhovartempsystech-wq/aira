# AIRA backend/client — complete fixture workflow

Source local commit: `dd17b01cd58ff5ea595f60dcf481b0495602429e` (D03-18A7, 5 November 2026).
This updates the prior D03-18A2 checkpoint under app/backend. Code, tests, scripts
and migrations are byte-identical to the local accepted snapshot. Documentation
copies omit internal links and personal paths. Local data, archives, secrets,
runtime binaries and unrelated uncommitted research/presentations are excluded.

## Verified behaviour

DOCX create/import → manual edits/undo/redo → tabs and autosave → close/restart and
explicit recovery → save/check/poll/stop/retry → results/filters/hides → confirmed
saved-copy export → reimport/reopen. Word processing timeouts and simultaneous-tab
autosave coordination are fixed with unchanged old acceptance checks and timeouts.

Full local gate: **7009 passed,45 skipped,24 subtests,exit0**, 1478.45s.
Standalone whole workflow: **1 passed**,37.77s, three synthetic DOCX, two host
lifetimes. Autosave uses advanced test clocks with real HTTP/DB checkpoint writes.
The working database schema/revision/counts remained unchanged.

## Start here

- [Workflow and frontend handoff](docs/docx-workflow-handoff.md)
- [Current product scope](docs/current-product-scope.md)
- [Final cycle result](docs/d03-18a7-result.md)
- [File client](docs/docx-client-files.md) and [workspace](docs/docx-client-workspace.md)

Run from this directory (app/backend):

```bash
bash scripts/check_docx_workflow.sh
```

Requires the project Python environment, Node and local Postgres.app runtime;
see the handoff for prerequisites. No global installation or existing-user-database
migration is performed by the demo. Generated examples live in ignored .runtime.
The standalone Ralph harness still requires monorepo Git-root adaptation before use.

This is an accepted client/backend fixture scenario, **not an end-user release**.
Real ML pack/quality, Anya's final UI/native picker, Windows-native and visual Word
acceptance, public TLS licensing and signed installers remain external gates.
Model and external licensing transport in the demo are explicitly synthetic.
The team's existing engine and frontend have not been replaced or automatically wired.
