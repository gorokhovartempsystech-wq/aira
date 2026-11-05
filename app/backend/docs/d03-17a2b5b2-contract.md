# D03-17A2b5b2 — Rich controls around physical tables

5 November 2026; F05/F06/F11, baseline b5b1 `00a7492`, 5634 passed +24 subtests, 45 skipped, 847 hashes. Enable unbound rich SDT wrappers around
block tables/paragraphs, individual rows/cells and blocks inside real cells. Preserve
original XML paths, physical cell flow and all existing table/style/field/note proofs.
No new product rules, DB, API, admission, editor/export, dependencies or runner changes.

## Allowed paths

New src/ara/docx_analysis/visible_control_tables/, own acceptance/edge tests,
contract/result/guide/queue. Four old files may gain private default-preserving hooks:
- tables/_context.py: parent_for(node,parent,recognized) defaults to raw parent;
- tables/_geometry.py: child_nodes(node) defaults to node's direct children;
- visible_tables/_reader.py: prepare_table_catalog(catalog) defaults to given catalog,
  called after original Reader anchors/events exist, before table/history indexes;
- visible_controls/_reader.py: control_content and control_block_plans helpers with
  unchanged b5b1 grammar/allowed blocks. The new profile overrides them, old API does not.
All previous tests immutable; hashes outside these four unchanged. Freeze/red,
implementation/review, targeted/full gate, readonly main V8, local selective commit.
Documented new-test preparation corrections allowed only with assertions unchanged.
No source/test/contract edits during full gate; continue the next bounded cycle.

## Evidence and structural meaning

[SdtContentBlock](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.sdtcontentblock?view=openxml-3.0.1)
contains saved block structures. [SdtContentRow](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.sdtcontentrow?view=openxml-3.0.1)
wraps a single row (unlike other SDTs it is not mapped/placeholder content).
[SdtContentCell](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.sdtcontentcell?view=openxml-3.0.1)
wraps a single cell. Only b5b1 known rich/non-placeholder/unbound properties accepted.
Zero content is permitted for optional empty sdtContent; an individual nonempty row/cell
control resolves to exactly one row/cell through nested same-level controls. Block
controls may contain several paragraphs/tables/nested block controls. Other saved
control types, automatic bindings, refresh, MC and unknown child kinds stay blocked.

## API and original-source proofs

build_control_table_snapshot and map_control_table_spans/span, same exact NoteSnapshot
and VisibleLimits under `docx-analysis/final-visible-control-tables-v1`. Reuse b5b1
whole-source preflight (including controls/fields), shared builder and shape mapper.
The shared original source and each real story tree stay intact, no XML reparenting,
node cloning, path renumbering, main-part relabeling or caller-provided capabilities.

New reader prepares its own table proof before table/history/revision indexes. Old
proof rejection is not admission: a fresh closed Context and GridGeometry must pass.
Move and section catalogs remain unchanged and retain their unsupported-context gates.
New Context uses original anchors and separately records original parents plus proven
logical parents. Only a validated structural sdt/sdtContent chain may mediate a logical
parent; property containers cannot be wrapped or promoted. A table must still belong
to body/actual tc, row to actual tbl, cell to actual tr. Nested table parent is the real
containing tc, never a wrapper. Inline controls are handled by b5b1 reader as before.

Control shape/property validation is cached privately per actual node and happens once
when needed for structural proof or reading; no public object carries XML or metadata
strings. Geometry's child iterator yields original proven children in source order,
with properties still in their proper PHYSICAL first position and history exclusions unchanged.
An empty control before tblPr/trPr/tcPr or tblGrid cannot promote late metadata into
a valid position; actual grid must follow only optional direct tblPr.
Grid spans/vertical merges, regular inferred grids, deleted cells, inserted rows/cells,
current property histories and table-style neutrality use their existing rules. No
new fallback for uneven row widths, gap inference, hMerge/cellMerge or row deletion.
Deleted-cell payload grammar beyond the old proof remains a gate.

The new table traversal follows actual rows/cells/control wrappers, using only nodes
present in the fresh table proof. Properties/history/deleted-cell branches remain
excluded as previously proven. It emits control boundaries even for empty controls,
so an open field cannot cross a wrapper silently. A paragraph's flow is the actual
cell or body; nested tables and note/story flows stay separate. Fields may span
several paragraphs inside the same block control/cell, but not leave that control,
cross rows/cells/section/story/nested-table boundaries. Existing merged continuation
proof still rejects retained text instead of silently discarding it.

Any failure is atomic: empty text/fragments/paragraphs/runs/references. Old field,
control and catalog public APIs keep old profiles/grammar. Source-backed mapping
rebuilds once, including empty queries, and rejects rehashed forged source/profile/
cell/part context. Global raw/semantic/output/manifest budgets remain enforced.

## Acceptance

Strict/custom UTF16, body-wrapped table, block control inside cell, row/cell wrappers,
nested combinations, interleaved ordinary rows/cells and controls, empty wrappers,
correct original paths/source slices and actual cell flow; notes/header/footer tables;
neutral styles/property histories/insertion/deletion/inferred grids/vertical merge;
fields inside one controlled cell, wrapper crossings including empty controls;
negative wrong-role wrappers, multi-row/cell controls, wrapped properties, unknown/
bound/placeholder controls, unequal grids, invalid merge/hidden payload, wrong namespace;
raw controls/tables budgets before semantic DOM, same-source mapping/old-profile guards,
inert subprocess. Native Word/Windows/layout and later content types remain separate.
