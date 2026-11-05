# Текущие свойства таблиц и история Word

`ara.docx_analysis.current_tables.read_current_table_catalog` строит отдельный
структурный каталог `docx-tables/current-properties-grid-v1`. Он читает текущую
сетку, интервалы ячеек и вертикальные объединения. Прежние свойства внутри
`tblPrChange`, `tblGridChange`, `trPrChange`, `tcPrChange` остаются в исходнике;
каталог фиксирует только тип истории и точные адреса marker/owner/previous root.
Значения author/date/id и исторический текст в DTO не переносятся.

History marker допустим только у реально распознанного текущего владельца, последним
элементом, не более одного. Проверяются namespace, атрибуты, id и контейнер с одним
корнем прежних свойств. Старые значения не подставляются вместо отсутствующей
текущей сетки и не исправляют ошибочную текущую геометрию. Ошибка в поздней таблице
не позволяет вернуть доверенный префикс: весь каталог получает blocked.

`CurrentTableLimits` наследует прежние численные лимиты и добавляет max_histories.
Весь main part, включая старые и неизвестные ветви, ограничивается до DOM: nodes,
depth, characters/namespace URI, tables/rows/cells/table depth и markers. Лимит
canonical manifest проверяется потоково. Только исходные bytes и SHA, без I/O.

`ara.docx_analysis.visible_current_tables` предоставляет
`build_current_table_snapshot`, `map_current_table_spans`, `map_current_table_span`.
Сигнатуры и immutable Visible DTO прежние; profile фиксирован как
`docx-analysis/final-visible-current-tables-v1`. Сначала из исходника один раз
строятся current catalog, MoveCatalog и StyleContext; proof нейтральности таблиц
использует этот же свежий context. Прежний стиль не участвует в выборе текущего.
Истории явно учитываются как excluded historical_table_properties/grid.

Mapping перестраивает доказательство из полного исходного DOCX один раз на batch,
включая пустой. Изменение только истории при одинаковом видимом тексте меняет SHA
и делает старый snapshot непригодным. Адреса исходных узлов и flow ячеек не сдвигаются
от удаления истории: её узлы вообще не удаляются. Старые profiles не расширяются.

Ограничения: это opt-in reader, пока не admission приложения. Current row/cell
insertions/deletions/merge revisions, ненейтральные стили, paragraph boundaries и
прочие DOCX части требуют дальнейших циклов. Whole-main MoveCatalog сохраняет свои
ограничения даже при move-маркерах внутри неподдерживаемого исторического payload.
Native Word parity и полный DOCX scope не объявляются завершёнными.
[Контракт](d03-17a2b3b1-contract.md), [результат](d03-17a2b3b1-result.md).
