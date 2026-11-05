# AIRA backend/client — native DOCX saving and recovery

Source local commit: `a791363112dd2f768bd4a7752a9dfb9e89fc6aea` (D03-19A through D03-19D, 5 November 2026).
The unrelated committed landing-page prototype under sites/ is excluded.
Code, tests, scripts and migrations are byte-identical to the accepted snapshot.
Documentation copies omit internal links and personal paths.

## Result

The existing fixture workflow now has trusted-host native DOCX saving adapters
(Python and optional Node), durable file associations and frozen save intents,
external-change detection, explicit Save As retargeting and recovery after restart.
The explicit V14 desktop database profile supports fresh databases and a backed-up
V13-to-V14 upgrade. The default remains V13; direct V12-to-V14 is rejected.
No HTTP endpoint accepts filesystem paths.

Full local gate: **7067 passed, 45 skipped, 78 warnings, 24 subtests, exit 0**,
1536.73 seconds. All 1036 source/test files and their inventory were verified
unchanged across the final gate. Three synthetic DOCX files were saved, reopened
and replaced through the Python adapter. Native Windows checks remain pending.

## Start here

- [Workflow and frontend handoff](docs/docx-workflow-handoff.md)
- [Current product scope](docs/current-product-scope.md)
- [Native Python file integration](docs/d03-19c-native-files.md)
- [Desktop V14 integration](docs/d03-19d-desktop-files.md)
- [Final validation](docs/d03-19d-result.md)

Run the existing fixture workflow from app/backend:

```bash
bash scripts/check_docx_workflow.sh
```

See the handoff for Python, Node and project-local PostgreSQL prerequisites.
This command is the existing fixture workflow, not final UI/native-picker wiring.
The standalone Ralph harness requires monorepo Git-root adaptation.

## Remaining release gates

This is not an end-user release. Final UI/file picker/IPC and shutdown coordination,
real ML pack and quality, native Windows and visual Word acceptance, public TLS
licensing and signed installers remain pending. The host must quiesce file writes
before releasing its data-home ownership. Portable replacement cannot exclude an
external writer racing after the final check. No ACL/xattr preservation is promised.
The demonstration model and licensing transport are explicitly synthetic.
Team files outside app/backend are preserved; secrets, user archives, runtime data
and unrelated uncommitted work are excluded. No merge or deployment is performed.
