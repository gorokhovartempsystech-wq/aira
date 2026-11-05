# D03-17A2b3a2 — итоговые текстовые потоки простых таблиц

4 ноября2026, после b3a1. Один bounded pure reader/map цикл: current explicit-grid
таблицы, nested cell flows, source-bound visible text. Не Word renderer/editor и не
application/ML admission. Полный DOCX остаётся прежним scope; table styles/revisions,
nonempty merge continuation/paragraph boundaries, numbering/settings/stories/fields
не считаются уже готовыми. Native Word gate не снимается.

Allowed новые `src/ara/docx_analysis/visible_tables/`,
`tests/acceptance/test_docx_visible_tables.py`,
`tests/docx_documents/test_visible_tables_edges.py`, этот contract/result/guide/queue.
До реализации оркестратор разрешает private shared extension только
`visible_main/_build.py`, `_canonical.py`, `_reader.py`: flow lookup, fixed default
style-context validation hook, выделение обычного block_plans(node) из plans.
Old public API/default profiles/fragment IDs/digests/guards и все старые tests неизменны.
Не менять catalogs/DTO schema/other source/ML/API/DDL/dependencies/runner/tasks/progress.
Main V8 и пользовательские материалы untouched, fixtures synthetic only.

## API, identity, integration

`ara.docx_analysis.visible_tables`:
`build_table_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None)`;
`map_table_spans(data, snapshot, *, requests, limits=None)`;
`map_table_span(data, snapshot, *, fragment_id, start, end, quote, limits=None)`.
Re-export same exact Visible* records/VisibleLimits/VisibleViewError. Public profile
fixed `docx-analysis/final-visible-tables-v1`, policy final-visible-no-comments-v2.
VisibleSnapshot schema unchanged. Fragment canonical preimage includes thisprofile,
story_anchor=mainbody and flow_anchor=body for mainparagraph or actual physicalcell
for cellparagraph. Same paragraphcoordinates, source SHA и flow входят в fragment ID.

No caller-supplied profile/catalog/reader. Source exact bytes/UUID/revision/SHA,
ZIP size beforehash, open_docx, aggregate main/styles preflight сохраняются. Prepare
строит TableCatalog и MoveCatalog из тех же bytes до reader DOM; XML caps из
VisibleLimits, остальные catalog caps default. Затем ровно1 StyleContext. Mapping
ровно1 rebuild всего snapshot для batch, bounded exact shape→full DTO equality;
пересчитанный caller hash не подтверждает подмену. Empty batches тоже проверяются.
Все старые/новые profiles взаимно отвергаются даже при перехешировании. No I/O.

Legacy Reader: validate_style_context(catalog) default no-op; flow_anchor(p) default
body. Его body/sectPr grammar неизменен; non-sectPr branch выделяется в block_plans:
requires ordinaryp, rsids/inline, returns[p]. Builder uses flow lookup bothinfragment
and hash; private canonicalflow defaultbody сохраняет все прежние expectedvalues.
New reader walks trusted table catalog, не принимает каталог как внешнюю capability.

## Потоки, visibility, coverage

Body order сохраняется, tables читаются row/cell order исходного XML, nestedtable
в своей позиции среди cell blocks. Each nonempty paragraph ownfragment, no joins
между cells/stories или сквозь table. Existing paragraph-boundary guards остаются.
Unicode codepoints, tab/break atoms, hidden-run rules, inserted/deleted content,
comment exclusions и hyperlinks наследуются из existing reader без sanitizer/copy.
Global two-LF fragment separator synthetic, не исходный символ.

GridSpan не дублирует cell text по столбцам. Restart/ordinary cell читается из своих
blocks один раз. Vertical continue допускает только canonicalempty paragraph blocks:
правильные rsids, нет дочерних элементов, только whitespace XML container text/tails.
Continuation получает excluded/merged_cell_continuation coverage, не fragment.
Любые run/properties/revision/text/nestedtable в continuation →
blocked unresolved_merged_cell_content, без потери содержимого. Catalog хранит все
physical blocks; reader не подменяет continuation origin blocks и не склеивает их.

TableCatalog blocked → table_catalog_blocked, MoveCatalog blocked→move_catalog_blocked,
ни main fragments/contexts/partial text. Main inline moves вне таблиц работают как
b2b2; moves внутри ячейки пока blocked по его структурному профилю. Unknown retained
flow/property/style сбрасывает весь main output; unread otherparts сохраняют blocked
coverage. Catalog main-only не даёт разрешения исключить остальные package parts.
Metadata events anchored: table_structure (table), table_grid (grid), table_row(row),
table_cell(cell), table_properties(propertycontainers). Ordinary coverage прежняя.

Global table default style в StyleContext (table,is_default) при наличии таблиц →
implicit_table_style. Любой explicit tblStyle → unresolved_table_style. Не гадать
basedOn/conditionalstyle rules. Unused nondefault table definitions не применяются
автоматически. Existing paragraph/character/default visibility остаётся обязательной.
Следующий resolver обязан обработать стили отдельно; этот отказ не новый продуктовый
scope. Ни settings/numbering/source attachments не объявляются accounted по MIME.

## Закрытая текущая property grammar

Table leaves: tblW,jc,tblInd,tblLayout,tblCellSpacing,tblLook,shd; boolean bidiVisual.
Table containers tblBorders,tblCellMar. Unknown/floating tblpPr/caption/description/
style exceptions/conditional properties → unsupported_table_properties (tblStyle
даёт свой fixedcode выше). Row leaves gridBefore,gridAfter,trHeight,wBefore,wAfter,jc;
booleans cantSplit,tblHeader,hidden. hidden true → unresolved_hidden_row; false
metadata. Cell leaves gridSpan,vMerge,tcW,shd,vAlign,textDirection; booleans noWrap,
tcFitText,hideMark; containers tcBorders,tcMar. hMerge/revisions уже blockedcatalog.

Property containers attrsnone/whitespace; closedchildnames/no duplicates. Formatting
leaves nochildren/nonwhitespace; attrs только Word namespace. Boolean leaves attrs
only optionalval, accepted existing boolean grammar. Geometry syntax/duplicates
проверены catalog fromsamebytes, не обходить черезhistoricalproperties. Borders:
top/left/bottom/right/start/end/insideH/insideV/tl2br/tr2bl; margins:top/left/bottom/right/
start/end. Composite children leafWordattrs, unique; unknowntext/property blocked.
No full XSD/layout/width validation claim, это accounting known formatting metadata.

Primary evidence прочитано4ноября:
[BiDiVisual](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.bidivisual?view=openxml-3.0.1)
меняет visual direction, XML сохраняет logical cell order: не переворачивать текст.
[HideMark](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.hidemark?view=openxml-3.0.1)
касается row-height calculation, не удаления cell text.
[Hidden](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.hidden?view=openxml-3.0.1)
касается row-end glyph/visibility interaction: true пока explicit blocked.
[Word clarification](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/be9bdcbb-f5ff-45f9-9120-44d8a545773b)
говорит, что hidden в table style игнорируется Word; будущий resolver обязан
учитывать контекст. Ни один источник не заменяет native Word parity acceptance.

## Acceptance и completion

Freeze/red. Literal text/order and exact original source paths: body before/after,
2x2 cells, repeated quotes acrosscells, nestedtables/multipleparagraphs, strictUTF16,
horizontalspan once/verticalorigin once+empty continuations; nonempty continuation
blocked; actualcell flow in canonicalfragmenthash; Unicode/tabs/comments/hidden/run
revisions внутриcell. Formatting+bidiVisual+hideMark не удаляют/переворачивают текст;
unknown/default/explicitstyle/hiddenrow/revision/paragraphboundary/cellmove guards.
Wrongprofile/forgedflow/piece/text/digest/source и emptybatch validation. Whole-input
XML limits beforeDOM, request/manifest/slice bounds; single eachcatalogperbatch;
freshprocess noFS/env/network/SQL/Word; original bytes unchanged.

Ни одного existingtest change. Newtest setup corrections допустимы с письменной
причиной без ослабления semantic assertions; review additions до full gate.
Required `bash scripts/check.sh`; previous727 hashes unchanged кроме3 разрешённых
shared files, readonlymainV8 snapshot, result/guide/localcommit. Затем следующий
bounded цикл по текущей autonomousкоманде. Native parity/application/realML/AnyaUI
и полноценные сложные DOCX readers остаются отдельными gates.
