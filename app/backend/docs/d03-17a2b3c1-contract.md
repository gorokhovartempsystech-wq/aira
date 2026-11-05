# D03-17A2b3c1 — source-backed missing/undersized table grid

4 November2026, F05/F06/F11. b3b2 full gate passed, commit 7f3b97b. One function:
resolve logical column count for regular retained rows when current grid is omitted,
empty or too short, then read/map text with original addresses. No pixel layout,
source mutation, column width guess, new document editor/admission or DB/ML change.
Full DOCX/native parity remains a broader gate; unresolved cases remain explicit.

New namespaces `src/ara/docx_analysis/grid_tables/`, `visible_grid_tables/`, tests
`test_docx_grid_tables.py`, `test_docx_visible_grid_tables.py`, own
`test_grid_tables_edges.py`, contract/result/guide/queue. Exactly ONE shared change:
visible_tables/_reader.py extract existing table_grid event into grid_event(table),
default exact same event at original grid node. table_plans delegates to it; new
reader overrides only to account derived grid without inventing source nodes. No other
old source/tests/deps/runner/tasks/schema/contracts modified. Verified b3b2 baseline:776 files.

## Evidence and limited derivation

[TableGrid](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablegrid?view=openxml-3.0.1)
specifies construction from actual contents when grid is absent.
[GridSpan](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.gridspan?view=openxml-3.0.1)
defaults missing span to1 and requires grid growth when needed.
Microsoft primary [WordprocessingML primer §2.5.6–2.5.7](https://download.microsoft.com/download/e/1/4/e14fb96f-83b8-4a2a-84db-7fa8acbe061a/Office%20Open%20XML%20Part%203%20-%20Primer.pdf)
describes placing cells in sequence and adding columns if their span exceeds the grid;
AutoFit starts with this same grid placement. We derive only logical intervals from
current retained spans; no widths/heights, visual arrangement or rendering proof.

[GridBefore](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.gridbefore?view=openxml-3.0.1)
has fallback behavior when larger than grid; [GridAfter](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.gridafter?view=openxml-3.0.1)
can be ignored on conflict. Therefore NEW derivation is restricted to rows with
before=after=0 and equal positive total span. We do not use gaps to invent extra
columns or guess their fallback order. Existing explicit grids whose row totals
already match may still use old validated before/after rules. Nonzero gap requiring
derivation, unequal row totals or current declared grid wider than rows remain
unresolved_table_grid. This is a conservative subset, not removal of remaining scope.

## Models and factory

`read_grid_table_catalog(data, *, source_sha256, limits=None)` in grid_tables.
GridTableLimits frozen slots inherits RetainedTableLimits (no new numeric field);
exact type validation/revalidation. Same errors TableCatalogError, package/source
identity guards, whole-main retained preflight (including excluded payload/history/
revision caps) before DOM, same actual RetainedContext. No XML copying/stripping.

GridTableCatalog(source_sha256,profile,status,main_part,tables,histories,revisions,
issues,catalog_sha256), profile `docx-tables/current-resolved-grid-v1`, indexed/absent/
blocked, failureatomic no partial tables/history/revisions. Reuse exact histories and
TableRevision/Row/Cell/Block. New GridTable has former PhysicalTable fields plus
`grid_mode` explicit/inferred/augmented and `column_count` positive boundedint.
`grid_anchor` is optional: None only for omitted current grid. `grid_columns` lists
ONLY actual original gridCol anchors, never fabricated columns. Thus inferred mode
has no anchor and empty columns; augmented mode has existing grid anchor/0..n actual
columns and column_count>len(columns). Explicit mode has matching positive count.
All anchors/collections reprhidden; no source text copied. Canonical streaming digest
same sorted compactJSON excludingcatalog_sha256 and bounded manifest.

## Geometry

Same table/row/cell actual context and current history/revision proof. A table has
optional tblPr then optional single current tblGrid before all rows. Missing grid
allowed here; duplicate/misordered/unknown children blocked as before. Present grid
attrsnone/container, all nonhistorical children exact gridCol leaves with optionalw;
known original tblGridChange excluded by current proof, not supplying current columns.
Malformed grid never becomes a request for inference. Empty valid grid may augment.

Normalize retained rows/spans/vertical origins with old bounded primitives, collecting
width=gridBefore+sum(retained spans)+gridAfter. No dense matrix, search or width parsing.
Require >=1 retained cell per row, >=1 row and all widths equal positiveN. If current
count==N>0: explicit, unchanged old geometry. If currentcount>N: unresolved. Otherwise
require all before/after=0; missinggrid→inferred, presentgrid→augmented, countN. Validate
N against existing max_grid_columns before allocating tables/manifest. All old merge
origin/current deletion/unknown row/cellMerge/hMerge limitations remain. Nested grids
resolve independently. Historical/deleted span values do not contribute to N.

## Text and batch mapping

`visible_grid_tables`: build_grid_table_snapshot/map_grid_table_spans/span, same
Visible DTO/signatures, fixed `docx-analysis/final-visible-grid-tables-v1`. Prepare
one fresh GridTableCatalog+MoveCatalog, fresh StyleContext/styleproof using existing
preflight/lifecycle. GridReader extends RetainedReader. Existing grid_event for any
presentgrid plus metadata derived_table_grid at source table for nonexplicit mode;
no event pretending a generated column was in source. Paragraph/cell flows and source
slice indices unchanged. Properties/styles/history/revision/hidden/comment/unreadparts
rules inherited, failureatomic main text. Batches rebuild original source once incl
empty; rehashed foreign snapshot, stale or forged derived coverage is invalid. Old
profiles still refuse missing/undersized grid, source bytes never change.

## Acceptance/gate

Freeze/red; regular omitted/empty/undersized explicit geometry, strict UTF16/custompart,
literal spans/origin/paths/text/mapping, independent nested grids, existing valid gaps,
no inference from history/deleted data, malformed current grid/globalatomic failure,
unequal totals/nonzero gap requiring derivation/oversized currentgrid/invalid merges,
technical caps/exactmanifest/source changes/DTOprofileforgeries/batchcounts/noI/O.
Previous tests untouched; new setup corrections only documented without weaker
assertions, review additions beforefull gate. scripts/check.sh required; all previous
hashes except one declared hook, read-only main V8 snapshot, result/guide/localcommit;
continue next independent cycle under active authorization.
