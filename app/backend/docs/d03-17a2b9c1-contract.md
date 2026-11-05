# D03-17A2b9C1 — opt-in table positions for the live DOCX editor

5 November 2026. Baseline `1aa0dbe`. F05/F06/F11/F12; prerequisite for frozen B9B.
B9B is incomplete: do not change its tests or claim the failed table-only scenario passed.
The prior body-only EditorSession/Registry defaults and their explicit table-only rejection
remain unchanged. This independent cycle adds a fixed opt-in policy, not a caller class registry.

Allowed old hooks: src/ara/app.py; src/ara/docx_editor/http.py and _registry.py;
src/ara/docx_package/checkpoint/_codec.py; src/ara/desktop/composition/_wiring.py.
New src/ara/docx_package/table_editor/; tests/acceptance/test_docx_table_editor.py and
 test_docx_table_editor_http.py. Docs this contract/result, docx-table-editor.md,
 development-queue.md and B9B-result.md; ignored .runtime. No other old source/tests,
wire schemas, SQL/migrations/dependencies, runner/tasks/progress or external publication.
Freeze/red first; pure/HTTP/negative/review and old body editor regression; all frozen B9B
scenarios; full check.sh plus explicit builder Ruff, immutable hashes and readonly mainV8.
New-test preparation-only corrections may retain all frozen assertions with written evidence.

TableEditorSession is an explicit fixed pure editor. If a top-level paragraph exists, its
initial caret and all existing body operations retain prior semantics. Otherwise select the
first projected paragraph in table traversal order, including nested/merged cells. Empty and
opaque-only packages still refuse. Exact main-part/source/path/codepoint selection validation
includes projected cell paragraphs; a cell is not flattened into body blocks or fabricated.

Cell insertion/replacement and a soft break splice only the selected simple paragraph,
using existing bounded lexical/run-format guards. Empty paragraphs/runs and Unicode are
handled without a fabricated body paragraph. Reject stale/out-of-bounds/foreign/opaque or
cross-paragraph edit selections atomically. Keep all other main XML bytes and auxiliary ZIP
parts; retained undo/redo restores exact packages and selection. Unsupported structural cell
commands and multiline/tab paste return unsupported_intent, not partial edit or generic500.
Body paragraph commands remain the old implementation. This is not table grid/row/merge editing
or native layout support; complex cell formats retain the existing conservative guards.

Checkpoint metadata wire/SQL stay unchanged: exact nested anchors can now be independently
validated against original package projection. Legacy pure EditorSession.restore still rejects
nested selections, while opted-in restoration supports them. A restored working copy has the
old revision/position0 and empty undo history; no durable undo promise. Invalid/forged metadata
and changed source cannot become a valid cell. Generic defaults remain body-only.

The boolean table_editor=False option is validated at Registry/app/transport admission before
resource work. Only explicit word_fixture composition enables it. No automatic content-based
switch in the legacy app and no user-facing hidden data migration. HTTP uses existing commands,
checkpoint/save/reconcile/recovery/content routes; source-pinned analysis receives the unchanged
saved bytes. Tests cover explicit behavior, table-only import/check/export, cell edit/checkpoint/
close/recover/save/exact export, stale requests and legacy rejection. Existing test statuses and
assertions are not modified to accommodate the new behavior.
