# D03-17A2b3b1 — текущие свойства таблиц при сохранённой истории Word

4 ноября2026. F05/F06/F11. Один функциональный цикл: прочитать current properties
таблицы/сетки/строки/ячейки, не применяя записанные предыдущие свойства. Source-bound
structural catalog + его versioned text/map integration — одна проверяемая функция.
Не принимать/отклонять revisions и не пересохранять original DOCX. Полный DOCX scope
не сокращён; row/cell insertion/deletion/merge, grid inference, paragraph boundaries,
nonneutral styles/native Word/application admission остаются отдельными gates.

Allowed новые `src/ara/docx_analysis/current_tables/`,
`src/ara/docx_analysis/visible_current_tables/`,
`tests/acceptance/test_docx_current_tables.py`,
`tests/acceptance/test_docx_visible_current_tables.py`,
`tests/docx_documents/test_current_tables_edges.py`, contract/result/guide/queue.
Только три private shared extensions разрешены до реализации:
- tables/_context.py: skip_history(node,parent,recognized) defaultFalse; hook после
  регистрации anchor/parent и до structural classification; True пропускает semantic
  descendants этой конкретной history, не whole-input preflight.
- tables/_geometry.py: выделить grid_columns(grid) с прежними attrs/container/positive
  count/budget/strict gridCol leaf checks; table использует возвращённые originalnodes
  для колонок/row width equality/anchors. Legacy default returns all children unchanged.
- visible_styled_tables/_reader.py: выделить prepare_styles(data,source,limits),
  возвращающий прежний pinned proof_factory после прежнего styles preflight. Старый
  prepare_reader затем так же вызывает прежний read_catalogs и StyledReader.
Старые profiles/public API/DTO/guards/тесты неизменны. Не менять другую source,
DDL/API/ML/deps/runner/tasks/progress. Main V8/архив/чужие файлы untouched.

## Структурный API и proof

`ara.docx_analysis.current_tables.read_current_table_catalog(data, *, source_sha256,
limits=None)`. Новые frozen slots CurrentTableLimits наследуют численные поля
TableLimits и добавляют max_histories20000. Exact CurrentTableLimits/ints, onlylower,
revalidation deleted/mutatedfields. Ошибки existing TableCatalogError invalid_input,
source_mismatch,table_limit_exceeded; DocxError для malformed/oversizepackage.
Source exactbytes/lowerhexSHA, archive size beforehash, open_docx. Oldread_table_catalog
не принимает новые limits/profile. Whole-input main preflight before semantic DOM
считает все прежние caps и обаWordNS history markers включая excluded/unknown
branches, attrs/text/tails/namespaceURI. Historycap до DOM, не после proof allocation.

Новый CurrentTableCatalog(source_sha256,profile,status,main_part,tables,histories,
issues,catalog_sha256), profile `docx-tables/current-properties-grid-v1`.
Statuses indexed/absent/blocked: это структурные факты, не finalvisibility/complete.
Reuse exact PhysicalTable/Row/Cell/Block и TableIssue. Histories tuple
TablePropertyHistory(kind,anchor,owner_anchor,previous_anchor), kind table/grid/row/cell.
anchor — marker; owner_anchor — реальные current properties/grid; previous_anchor —
его единственный original child. Всё в original mainpart/path/source, no copied tree.
No rawXML/text/author/id/date values in historyDTO/repr; anchors/collections hidden.
Canonical sorted compactUTF8 dataclassJSON excludingcatalog_sha256, streaming bounded
manifest. Sortedsourcehistoryorder, existingtablepreorder. Any structural failure →
no tables AND no histories, one fixedissue; no trusted partialprefix.

## Context и грамматика history

Known markers: tblPrChange→tblPr, tblGridChange→tblGrid, trPrChange→trPr,
tcPrChange→tcPr. Только direct child реального recognized current owner из того же
Wordnamespace; owner membership, не name-only ancestor search. Не более1marker для
owner, lastchild (после currentproperties/columns). Required id matching existing
signed decimal [+-]?[0-9]{1,20}. tblGridChange attrs onlyid; остальные id/author/date.
Allattrs Wordnamespace, no w16du extension guessed. Marker whitespace container,
ровно1child с appropriate oldpropertyname. Previousroot attrsnone/whitespace container;
его property children opaque historical payload, no interpretation/activation.
Entire subtree counts in preflight, even nested table/move/hidden/unknown tags.
Wrongowner/mixednamespace→unsupported_table_context. Malformed/duplicate/misordered
history→invalid_table_history. Body wrappers/table structural rows/cells/current
revisionmarkers сохраняют oldguards; никакой global descendant whitelist.

Current grid uses только direct gridCol вне validated tblGridChange, >=1column.
Исторические числа/границы/стили не заменяют currentwidth/span/merge. Current grid
still explicit, rowintervals mustequalgrid, bounded vertical origins, canonicaltable
records. No inferenceaugmentation/hMerge/cellMerge. Noncurrentbadproperties excluded
as history; invalid CURRENT geometry remains blocked even if history was valid.

## Text/map integration

`ara.docx_analysis.visible_current_tables`: build_current_table_snapshot,
map_current_table_spans/map_current_table_span, same Visible* API/DTO/limits/errors.
Profile `docx-analysis/final-visible-current-tables-v1`, samevisiblepolicy. Fresh style
preflight/proof fromsharedhelper, exactly1CurrentTableCatalog +1MoveCatalog +1StyleContext
and table-style proof per table-containing build/batch. Source rebuild onceperbatch,
exactDTO equality incl emptybatch; no source stripping/sanitizing/re-serialization.
CurrentTableLimits XML fields inherit VisibleLimits; othercaps defaults. Catalogerrors
translated as priorreaders. Unreadparts and oldstyles/boundary/hidden/mergedcontinuation
rules unchanged; no caller-supplied catalog/profile capability. The existing whole-main
MoveCatalog also keeps its closed context checks: a move marker hidden in malformed
historical property payload remains blocked, never treated as current text/movement.

CurrentReader extends StyledReader with exactfreshcurrentcatalog. Emits one excluded
historical_table_properties event per non-grid history and historical_table_grid per
grid history at originalmarker. Current property reader accepts ONLY exactmarker
anchors alreadyproved bycurrentcatalog, allother branches use oldclosedgrammar.
Historical tblStyle/hidden/gridSpan/vMerge/cellDel are never activated. Wrong current
style/currenthidden/currentgeometry still blocks. Text/flow/slices use real source
nodes and indices that include originalhistorychildren. Existingprofiles stillreject
these histories, new/old mappers mutuallyreject profiles/rehashes.

## Primary evidence / unresolved structural revisions

Read4Nov:
[TableGridChange](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablegridchange?view=openxml-3.0.1),
[TablePropertiesChange](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablepropertieschange?view=openxml-3.0.1),
[TableRowPropertiesChange](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablerowpropertieschange?view=openxml-3.0.1),
[TableCellPropertiesChange](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablecellpropertieschange?view=openxml-3.0.1)
различают currentsiblings и previouschild. Gridchange attrs отличаются от otherchanges.
[Deleted row](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.deleted?view=openxml-3.0.1)
сам по себе НЕ объявляет текст/ячейки удалёнными; нельзя просто выкинуть subtree.
[CellDeletion](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.celldeletion?view=openxml-3.0.1)
имеет другую семантику. Их topology/boundaries требуют отдельного evidence/контракта,
в этомцикле old explicitrefusals. Wordконтроль недавно timeout, не повторятьбезnewstate.

## Acceptance / finish

Freeze/red. Literal currentgrid/style/text contrarytohistory, allfour historykinds,
strict UTF16/custompart, exact originalmarkers/owner/previous/cell/slice paths,
currentverticalorigin/span vsoldconflict, unknownhistorychildren accounted butlimited,
malformed/envelope/wrongowner/duplicate/currentunknown blockers, globalatomicfailure,
unchangedoldprofiles, source/style/DTO/hashforgery/emptybatch, maxhistorybeforeDOM,
wholeinputlimits/exactmanifest/digest/noI/O/immutable and repr. NativeWord/fullDOCX
claims withheld. Existingtests unchanged; newsetupcorrections onlywithwrittenreason
and no weakerassertions; review additions beforefullgate. scripts/check.sh,750 previous
hashes exceptexact3allowedsharedchanges, readonlymainV8 snapshot, guide/result/local
commit, затем следующий boundedcycle по действующей autonomousкоманде.
