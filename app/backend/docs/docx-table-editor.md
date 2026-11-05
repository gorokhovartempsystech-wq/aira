# Opt-in cell editing for imported DOCX

`TableEditorSession` is a fixed opt-in extension of the existing body editor. Generic
`EditorSession`, `EditorRegistry(runtime)` and `create_app(document_runtime=runtime)` retain
the previous body-only behavior. Enable `table_editor=True` explicitly at app/Registry creation;
the owned `word_fixture` composition selects it. The option must be a real boolean.

The original projection keeps tables, rows, cells and nested blocks. An existing top-level
paragraph remains the initial caret target; otherwise the first projected cell paragraph is
selected. Cell positions use their full original paragraph anchor and Unicode codepoint offset.
`capture` can select them without creating an artificial body paragraph. Plain and merged cells,
nested tables and empty cells are covered by acceptance; this is not native visual rendering.

Inside a simple cell paragraph, `insert_text` replaces the selected range and `insert_soft_break`
inserts a Word line break. Single-line plain paste is supported within the100000-character
cell insertion limit. Formatting is inherited from the existing run at the caret. All bytes
outside the selected paragraph and every auxiliary ZIP part are preserved; undo/redo retain exact
packages and selections. Legacy body typing/paste/Enter/break behavior uses its old implementation.

Cross-paragraph/cross-cell text replacement, Enter/join in a cell, multiline or tabbed cell paste,
and complex guarded cell content refuse explicitly without publishing a partial edit. There are
no row/grid/merge manipulation tools in this cycle. Physical cells in a merged table remain their
original source cells; no visual flattening or rebasing is invented. Fields, hyperlinks, ranges,
annotations and unsupported formatting retain the conservative lexical editing guards.

Checkpoint metadata retains its exact wire shape and SQL representation. Nested selection is
revalidated against the original package, including its source hash, part, path and offset.
An opted-in session can close and recover this working copy, then save/export through the existing
routes. Recovery restores bytes/caret, with revision/position0 and no durable undo history.
The legacy pure restore still refuses nested positions. A legacy client opening a new table-only
checkpoint receives refusal; it does not destroy, convert or replace the stored draft.

This supplies the previously missing editor admission for B9B's table-only Word checks. Analysis
still uses its separately verified visible-source policy, and the desktop mode remains an
explicit fixture. It does not claim a finished GUI, real ML, full table editing or Word layout.
