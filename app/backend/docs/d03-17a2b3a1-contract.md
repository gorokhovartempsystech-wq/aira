# D03-17A2b3a1 — физическая сетка таблиц DOCX

4 ноября2026. Bounded structural prerequisite из A2b3a: индекс прямых текущих
таблиц/строк/ячеек с source anchors, spans/vertical merge origins и ordered blocks.
Это НЕ итоговый вид/стили/layout/visibility, не permission читать/редактировать текст
или complete coverage. Paragraph/native Word gates не снимаются. После catalog —
отдельный table-flow reader b3a2; revision tables b3b остаётся в исходном объёме.

Allowed новые `src/ara/docx_analysis/tables/`,
`tests/acceptance/test_docx_table_catalog.py`,
`tests/docx_documents/test_table_catalog_edges.py`, этот contract/result/guide/queue.
Прежние source/tests/профили/ML/API/DDL, dependencies/runner/tasks/progress/AGENTS
не менять. Основная V8 БД и пользовательские материалы untouched. Synthetic only.

## Основание и сознательные границы

Primary Microsoft docs прочитаны4ноября:
[gridSpan](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.gridspan?view=openxml-3.0.1):
по умолчанию1; переполнение может расширять сетку. [tblGrid](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablegrid?view=openxml-3.0.1)
может восстанавливаться по содержимому, если отсутствует.
[gridBefore](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.gridbefore?view=openxml-3.0.1)
и [gridAfter](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.gridafter?view=openxml-3.0.1)
задают пропуски краёв, не пустые ячейки; конфликтующий gridAfter может игнорироваться.
Наш первый профиль требует явную согласованную сетку, вместо inference возвращает
unresolved_table_grid. Такой отказ НЕ объявляет любой такой документ невалидным.

[vMerge](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.verticalmerge?view=openxml-3.0.1)
продолжает объединение по тем же столбцам; отсутствие элемента завершает цепочку.
[Отсутствующий val](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.verticalmerge.val?view=openxml-3.0.1)
означает continue. [hMerge](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.horizontalmerge?view=openxml-3.0.1)
— другая, legacy форма; в этом профиле blocked без конвертации исходника.

## API и records

`read_table_catalog(data:bytes, *, source_sha256:str, limits=None)->TableCatalog`.
Exact bytes/lowerhex64+actualSHA, archive size beforehash, existing open_docx/DTD/ZIP
protection. Никакого FS/env/network/Word/SQL ни при import, ни при read.
Fixed TableCatalogError invalid_input/source_mismatch/table_limit_exceeded;
malformed package сохраняет existing DocxError. Никогда XML/parser text в errors.

Frozen slots, anchors/collections/part names repr-hidden:
- TableBlock(kind paragraph|table,anchor).
- TableCell(anchor,properties_anchor,column_start,column_span,vertical_merge,
  merge_origin,blocks tupleTableBlock).
- TableRow(anchor,properties_anchor,grid_before,grid_after,cells tupleTableCell).
- PhysicalTable(anchor,parent_cell_anchor,properties_anchor,grid_anchor,
  grid_columns tupleSourceAnchor,rows tupleTableRow).
- TableIssue(code,anchor).
- TableCatalog(source_sha256,profile,status,main_part,tables,issues,catalog_sha256).
Profile `docx-tables/main-physical-grid-v1`. No complete/text/visible_cells claims.

Status absent только когда relevant table markup отсутствует в main. indexed —
структурные direct-current факты; даже opaque styles/hidden/unsupported paragraph
content могут сосуществовать и должны отдельно проверяться reader. blocked —
весь tables tuple пустой, одна deterministic issue, никаких частичных ready tables.
Catalog main-only, другие package parts не объявляются прочитанными.
Canonical SHA: sortedkeys compact UTF8 JSON ensure_asciiFalse allow_nanFalse над
asdict без catalog_sha256. Streaming size budget перед завершением digest, no
caller-provided DTO trust/deserialization. Исходные bytes неизменны.

Таблицы в document preorder, строки/ячейки в XML order. Column start zero-based,
span positive, interval halfopen. merge_origin=self для none/restart, anchor первого
restart для continue. Каждая physical continuation cell записана один раз со СВОИМИ
blocks, даже если там есть текст; не заменять её содержимое blocks родителя и не
исключать по предположению. Будущий reader решает final visibility отдельно.
Nested table — ordered block внутри cell и отдельный PhysicalTable с parentcellanchor;
границы flows сохраняются, cross-cell paragraph joins запрещено угадывать.
Anchors exact main part/SHA/element-only child indices, XML comments/PIs не считаются.

## Прямой структурный grammar

Strict/transitional namespace. Сканировать ВСЕ main nodes, включая history/unknown/
excluded contexts. Relevant structure: tbl/tblPr/tblGrid/gridCol/tr/trPr/tc/tcPr,
gridSpan/vMerge/hMerge/gridBefore/gridAfter и table revision tags. Mixed Word namespace
для relevant structures blocked. tbl допускается только напрямую в body либо в
распознанной tc. tr только напрямую в своей tbl, tc только напрямую в tr. Relevant
nodes в SDT/customXml/deleted/textbox/unknown wrappers/history не исчезают из индекса.

Table: optional tblPr первым, ровно1 tblGrid перед >=1tr. Row: optional trPr первым,
затем >=1tc. Cell: optional tcPr первым, затем >=1 blocks p/tbl. Только whitespace
между структурными детьми. tbl/tc attrs none; tr attrs rsidR/rsidRPr/rsidDel/rsidTr
optional exact8hex, только metadata, не row deletion. Row tblPrEx/extension attrs
пока unsupported. Свойства root containers attrsnone. Остальные formatting children
внутри properties не интерпретируются catalog и не считаются разрешёнными reader.
Но relevant structural/revision tags внутри них обязательно проверяются глобально.

tblGrid children только gridCol (>=1), each leaf attrs optional Word w only,
без чтения ширины/геометрии страниц. Порядок колонок, не width, задаёт координаты.
Direct tcPr/gridSpan: leaf required val, positive boundeddecimal, default1 ifabsent.
Direct tcPr/vMerge: leaf optionalval restart/continue, absentval→continue, noelement→none.
trPr/gridBefore и gridAfter: leaf requiredval nonnegative decimal, default0. Никаких
дубликатов structural properties/containers. Numeric grammar `[+]?[0-9]{1,20}`,
leadingzeroes normalized, minus/space/hugelexeme rejected as invalid_table_markup.
This is technical profile bound, not complete XSD validation.

Каждая row: before+sumdirectspans+after == declared grid count. Missing/empty grid,
overspan или несовпадение — unresolved_table_grid, без исправления/phantom cells.
Число колонок/любой span/before/after больше установленного cap → limit error.
Continue требует exact(start,span) active group в непосредственно предыдущей строке
той же таблицы. Firstrow/orphan/misaligned/interrupted continuation → invalid_vertical_merge.
Restart начинает новый origin; none/gap завершает прежний group. Не разворачивать
spans в плотную матрицу/repeated aliases, алгоритм linear по records, bounded paths.

Legacy hMerge, tblPrChange/tblGridChange/trPrChange/tcPrChange/cellIns/cellDel/cellMerge,
ins/del непосредственно в trPr → unsupported_table_revision. Inline ins/del внутри p
не означает rowrevision и может сосуществовать с catalog (текст всё равно не читается).
Other unknown table/row/cell child → unsupported_table_context. Не обходить history,
не выводить текущую logical grid из marker имени без context.

Fixed issue codes unsupported_table_context,invalid_table_markup,
unresolved_table_grid,invalid_vertical_merge,unsupported_table_revision.
Источник issue — соответствующий original node. Global context/revision scan preorder
перед нормализацией geometry; затем tablepreorder/roworder/cellorder deterministic.

## Bounds и приёмка

TableLimits exactint1..default, revalidate mutatedlimits:
max_xml_nodes100000,max_xml_depth128,max_xml_characters8388608,max_tables1000,
max_rows10000,max_cells10000,max_grid_columns1024,max_table_depth16,
max_blocks20000,max_manifest_bytes33554432.
Main XML characters incltext/attrs/tails/namespaceURI, nodes/depth/tables/rows/cells/
table nesting считаются до semantic DOM, включая исключённые branches. Grid/blocks
и canonicalmanifest bounded после parse. No truncation, all original limits remain.

Freeze/red; independent literal2x2grid, horizontalspan, verticalrestart/emptycontinue/
explicitcontinue, reset/nonecloses/gaps; nestedtable owncoordinates/preorder/blocks;
continuation retainsownsourceblock, noalias; strictUTF16/custommain/widthindependence.
Malformed/duplicate/implicitgrid/overspan/numbers/nesting/history/unknowncontext/mixedNS
cases. Inlineins/del compatible, rowrevision blocked. Bounds beforeDOM includingnamespaces,
sourcehash/immutability/deterministicdigest/frozenDTO/private-repr, freshprocessnoIO.
Oldvisible_main и visible_moves stillblocktables. No weakeningprevious tests.
Newtestpreparation may be corrected with writtenreason and same semantic assertions;
review additions beforefull. Required full `bash scripts/check.sh`, previous718hashes
unchanged, readonlymainV8 snapshot/result/guide/localcommit. Then next bounded cycle
under current explicit autonomous instruction. Native Word/layout and final-reader
admission remain separate, не объявлять full DOCX support по результату catalog.
