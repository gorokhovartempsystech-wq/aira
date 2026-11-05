# D03-17A2b3b2 — retained table cells with tracked insertions/deletions

4 Nov 2026; F05/F06/F11. b3b1 full gate passed, implementation commit 7a9441c.
One functional cycle: structural proof and source-backed visible mapping for inserted
rows/cells and deleted cells when the explicit CURRENT grid exactly fits retained
rows. No source mutation, accepting/rejecting revisions, application/ML admission,
DB/API/dependencies/runner/tasks/old tests. Native Word parity remains a release gate.
Full DOCX product scope unchanged; narrower reader does not discard unresolved scope.

Allowed NEW namespaces `src/ara/docx_analysis/retained_tables/` and
`src/ara/docx_analysis/visible_retained_tables/`, acceptance `test_docx_retained_tables.py`,
`test_docx_visible_retained_tables.py`, own `test_retained_tables_edges.py`, contract/
result/guide/queue. **No old source change required**: use existing private virtual
CurrentContext.skip_history, CurrentGeometry.children and CurrentReader/property hooks.
All previous763 hashes preserved; b3b1 baseline verified after its full gate.

## Primary facts and explicitly limited inference

[Inserted row](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.inserted?view=openxml-3.0.1)
and [inserted cell](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.cellinsertion?view=openxml-3.0.1)
mark current retained structure; row insertion does not determine child text revisions.
[Deleted cell](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.celldeletion?view=openxml-3.0.1)
is logically absent despite physically stored XML. [Table grid](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablegrid?view=openxml-3.0.1)
describes current shared column boundaries; construction of missing grid is specified
but not implemented by this reader. Our conservative derivation requires every retained
row to exactly match the explicit current grid after deleted cells are excluded.
Inconsistent/past-only/missing grid is blocked, not repaired by inferred widths.

[Deleted row](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.deleted?view=openxml-3.0.1)
does not declare its cells/text deleted. Every current row del remains blocked here,
including a row with no retained cells. All current cellMerge/hMerge remain blocked.
[Merge revision enum](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.verticalmergerevisionvalues?view=openxml-3.0.1)
labels rest as split; do not blindly map it to ordinary vMerge restart. Merge revision
and paragraph/row boundary topology remain separate evidence work, not an omission
from agreed product scope. Whole-main MoveCatalog keeps its existing guards, even
for markers inside deleted cells. Unread package parts remain visible blockers.

## API, DTO and caps

`ara.docx_analysis.retained_tables.read_retained_table_catalog(data, *, source_sha256,
limits=None)`. Exact RetainedTableLimits inherits CurrentTableLimits, adds max_revisions
20000. Counts every WordNS ins/del/cellIns/cellDel/cellMerge marker in whole main before
any semantic DOM, including histories/deleted/unknown branches. Existing all-input
nodes/depth/chars/namespace/table/row/cell/history caps remain; no prefiltered XML.
Exact bytes/lower SHA/max package before hash/source match and fixed safe errors as
old catalogs. Reuse TableCatalogError invalid_input/source_mismatch/table_limit_exceeded.

RetainedTableCatalog(source_sha256,profile,status,main_part,tables,histories,revisions,
issues,catalog_sha256), frozen slots. Profile `docx-tables/retained-current-grid-v1`,
statuses indexed/absent/blocked. PhysicalTable/Row/Cell/Block and history DTO reused.
TableRevision(kind,anchor,owner_anchor,subject_anchor), kinds inserted_row/inserted_cell/
deleted_cell. Anchor original marker, owner current trPr/tcPr, subject original tr/tc.
Source-order records, hidden repr of anchors/collections; no id/author/date/text copied.
Tables contain only retained actual structure. Deleted cell descendant tables/histories
not current records; the single excluded-cell proof accounts for their whole payload.
Canonical stream digest same sorted compactJSON except catalog_sha256; exact manifest
cap. Any structural failure clears tables/histories/revisions, returns one fixed issue.

## Closed context rules

Retained row ins / cellIns must be direct leaf of actual recognized trPr/tcPr in same
WordNS, <=1 revision per owner. Attrs only id/author/date, required signed decimal
id 1..20digits, whitespace leaf/tail. Wrongowner/namespace→unsupported_table_context;
malformed/duplicate/conflicting revisions→invalid_table_revision. Row del and cellMerge/
hMerge keep unsupported_table_revision. Content inside retained cells follows existing
inline ins/del/hidden/style rules independently of insertion metadata.

Deleted cell is recognized at actual same-namespace tc whose parent is recognized tr,
before visiting its descendants. Require tc attrsnone/whitespacecontainer, one tcPr
first, tcPr attrsnone/whitespacecontainer, exactly1 direct same-namespace cellDel with
valid leaf/attrs/id; no simultaneous cellIns/cellMerge/hMerge (conflict blocked).
At least1 following original p/tbl block, no other direct cell child kind. Historical
property envelopes and rest of excluded cell payload remain opaque; all counted in
preflight. Proof does not require interpreting deleted gridSpan/vMerge/visibility.
A duplicate/misordered tcPr, foreign marker or malformed deletion never authorizes
skipping contents. Deleted-cell proof is registered with original path including all
physical siblings; no synthetic nodes, copied tree or shifted XML indices.

Context hook skips only that proven deleted cell's semantic descendants; current
retained cells and nested tables still have actual ownership validated normally.
Geometry filters deleted cells from row's returned cell sequence while keeping all
original nodes/anchors. Retained row must have >=1 cell and exact grid width including
existing gridBefore/After and spans. Ordinary vertical continuation requires retained
previous origin with same interval, as before. No cell deletion closes, starts, or
repairs a merge. CurrentHistory catalog still rejects revisions, all old behavior stays.

## Visible profile

`visible_retained_tables`: build_retained_table_snapshot, map_retained_table_spans/span;
fixed `docx-analysis/final-visible-retained-tables-v1`, same Visible* types/signatures.
Preparation: same styles preflight, one fresh RetainedTableCatalog+MoveCatalog, one
StyleContext and neutral table style proof; no caller-supplied DTO/profile capability.
Limits inherit Visible XML values; all other catalog caps default. Mapping rebuilds
source once per batch including empty; forged DTO, profile/rehash, changed deleted
text/history/source still rejected. Table selection only for retained actual tables.

Reader extends CurrentReader; properties accept insertion markers only when present
in its exact fresh revision proof. Metadata inserted_table_row/inserted_table_cell
at marker, excluded deleted_table_cell at whole original subject cell. Other histories
use unchanged excluded events. Deleted text/nested tables never becomes fragments,
context or style usage. Retained hidden/unknown/merged-continuation guards unchanged;
any failure clears all main text. Comments remain saved/not analyzed. Source unchanged.

## Acceptance and finish

Freeze/red before source. Literal mixed physical/retained order/grid/paths, row and
cell insert independent inline revisions, deleted nested unknown payload excluded,
current history integration, exact source batch mapping and deleted-only source change,
strict UTF16/custom parts, duplicate/malformed/fakeowner/wrongns/globalatomic blockers,
all-deleted-row/current row deletion/merge refusals, retained merge origin failures,
whole-input caps beforeDOM including deleted data and malformed markers, canonical
manifest/digest/immutable/repr and no application I/O in fresh process. Existing tests
untouched; own setup corrections documented without weaker behavior assertions, review
additions before full gate. scripts/check.sh required, previous hashes/read-only main
V8 snapshot, guide/result/selective local commit. Continue next bounded cycle under
active user authorization; no native/release/complete DOCX claim.
