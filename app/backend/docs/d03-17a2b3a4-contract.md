# D03-17A2b3a4 — source-backed styled table text and mapping

4 ноября2026. F05/F06/F11, after b3a3. Separate opt-in pure reader accepting proven
neutral table styles. Full DOCX/native Word/application admission remain incomplete.
Current main V8, ML/SQL/API/runner/tasks/progress/oldtests unchanged. Synthetic only.

Allowed new `src/ara/docx_analysis/visible_styled_tables/`,
`tests/acceptance/test_docx_visible_styled_tables.py`,
`tests/docx_documents/test_visible_styled_tables_edges.py`, contract/result/guide/queue.
Three authorized private shared extensions only:
1. visible_main/_reader.py: extract existing ordinary-format else into
   formatting_property(node,kind), default same closedgrammar/leaf/Wordattrs.
2. visible_tables/_reader.py: extract fresh Table/Move catalog preparation helper,
   default factory stillTableReader; read_properties(anchor,kind) default delegates
   ephemeral Properties(self).read, used for table/row/cell. No retained helpercycle.
3. visible_tables/_properties.py: table_style(node) default unresolved_table_style,
   extended(node,kind) default refusal; read routes existing branches through hooks.
Old profiles/API/DTO/default hashes/guards unchanged. No other oldsource/test edits.

## Fixed API and proof lifecycle

`ara.docx_analysis.visible_styled_tables`: build_styled_table_snapshot(data, *,
document_id, storage_revision, source_sha256, limits=None), map_styled_table_spans
(data,snapshot,*,requests,limits=None), map_styled_table_span with existing exact
fragment_id/start/end/quote keywords. Same Visible* records/limits/errors reexports.
Profile `docx-analysis/final-visible-neutral-tables-v1`; existing policy final-visible-
no-comments-v2. Source/flow in fragment ID as b3a2, fixed profile, no caller reader/
catalog/profile overrides. Every mapping batch including empty validates exactshape
and rebuilds original whole source once; forgedhash/flow/stylecontext/profile rejected.

Shared builder sourceidentity/size/hash/ZIP and aggregate main/stylespreflight retained.
New prepare additionally runs b3a3 whole stylespart preflight BEFORE any style semantic
DOM; captures original bytes and prooflimits, then builds exactly1Table+1Move catalog
using sharedhelper. Builder reads exactly1StyleContext; newreader consumes this fresh
context through private table_styles._read.catalog to build proof once if tables exist.
No caller DTO accepted. No tables→no table proof required, old paragraph rules remain.
Proof limits XMLnodes/depth min(VisibleLimits,styleslimits); chars fromVisibleLimits;
styles/chainDepth/issues from styleslimits, manifest from VisibleLimits; other proof
caps defaults. All proof/context cap errors retain existing staticVisible/error types;
TableStyleError table_style_limit_exceeded translated view_limit_exceeded. Public
catalog API unchanged. No filesystem/env/network/SQL/Word/applicationI/O.

## Source-derived style selection

Each physical table independently chooses its explicit direct tblPr/tblStyle, otherwise
unique default table style from sourcecontext. No implicit inheritance of outertable's
selector, no hardcoded TableNormal/TableGrid, no external templates. Explicit selector
leaf requires onlyval, length1..253, unique. Malformed→unsupported_table_properties.
Missing explicit ID→missing_table_style; non-table kind→table_style_type_mismatch;
selected nonneutral definition/ancestor/conditionalbranch→unresolved_table_style.
No default and no selector means no table-style contribution. Bad default is irrelevant
when every table explicitly selects an independent neutralstyle; still applied/blocked
for any table without explicit selector. Unused nondefault badstyles don't block.

This is an interpretation of ECMA376-1 §17.7.4.17 default(type) at printedp642:
objects with no explicitstyle use per-kinddefault; withoutdefault no suchproperties.
Primary localextract `.runtime/d03-17a2b3a4-ecma-style-identity.txt` from official
[ECMA376 5th2016](https://ecma-international.org/wp-content/uploads/ECMA-376-1_5th_edition_december_2016.zip).
[ReferencedTableStyle](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablestyle?view=openxml-3.0.1)
defines explicit hierarchy. [defaultTableStyle](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.defaulttablestyle?view=openxml-3.0.1)
in settings concerns newly inserted tables, does not re-style an existing document.
Settings remains unreadblocked, never used as per-kind default. Missing explicitstyle
is conservatively blocked despite specification fallback. NativeWordparity stillgate.

Before plans, validate selectedstyle of ALL physicaltables (including nested); any
unresolved selection clears all mainfragments/contexts as before. Metadata event
`table_style_proven` anchored at each table withselectedneutralstyle; selectors counted
by table_properties envelope. No style properties are rewritten as direct rPr. Existing
paragraph/character/docdefaults/direct hidden and paragraphboundary guards unchanged.
Neutralproof excludes all visibility and boundary properties (including false), so it
cannot override those guards. Samephysicalcellorder, mergedcontinuation/empty/move/
hidden/revision/comment rules, no crosscelljoins/duplicateorigin/text search.

Conditional metadata allowed ONLY in newprofile:
- `cnfStyle` under current pPr/trPr/tcPr: exactleaf with allowedWordattrs val plus
  firstRow,lastRow,firstColumn,lastColumn,oddVBand,evenVBand,oddHBand,evenHBand,
  firstRowFirstColumn,firstRowLastColumn,lastRowFirstColumn,lastRowLastColumn.
  val ifpresent exactly12binarychars; other flags strict existingbool lexemes.
  Multiple flags and val can coexist: all candidate branches provenneutral, no
  region choice/precedence guessed. Unknownattrs/children/text/duplicateproperties
  stillblocked. Metadata conditional_table_format at originalnode. Outside-table
  paragraph property remains metadata (spec says ignored there). Not allowed inrPr/mark.
- Direct tblStyleRowBandSize/tblStyleColBandSize formatting leaves knownWordattrs;
  no children/text. They cannot affect text when all conditionalbranchesneutral.
No other property/numbering/settings/story/MC support added. Coverage old unreadparts
retained; stylesaccounting onlywhen allmainusage validated bysharedbuilder.
[cnfStyle source](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.conditionalformatstyle?view=openxml-3.0.1).

## Acceptance/gate

Freeze/red. Literal text/sourcepaths/default/explicit/inherited/allregions/nestedstyles,
badunused/default overridden versus actualimplicit use; exactcnfStyle contexts/guards,
Unicode/hidden/style/direct/revisions/comments/mergedcells, oldprofiles unchanged,
source change in styles invalidates oldproof even identicaltext, rehashedDTO/emptybatch
reject, onceeachcatalog perbatch, preDOM style/namespaces/regions caps, own inherited
limit/manifest/requestcaps, noI/O, bytes unchanged. Old tests untouched; own setup
corrections only documentedwithoutweakening semanticassertions, review additions
before fullgate. scripts/check.sh required,743 previoushashes exceptexact3allowed
privatechanges; readonlymainV8 snapshot, result/guide/localcommit. Continue nextbounded
cycle perautonomouscommand, without claiming fullDOCX/application/native completion.
