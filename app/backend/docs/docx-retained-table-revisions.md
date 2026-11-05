# Добавленные строки/ячейки и удалённые ячейки Word

`ara.docx_analysis.retained_tables.read_retained_table_catalog` строит отдельный
`docx-tables/retained-current-grid-v1`. В records сохраняются исходные адреса вставки
строки, вставки ячейки и удаления ячейки; численная сетка описывает только оставшиеся
ячейки. Перед исключением удалённой ячейки проверяются её реальный владелец, tcPr,
точная метка удаления и отсутствие конфликтующих меток. Произвольный cellDel под
другим узлом не разрешает пропускать содержимое.

Все строки должны точно соответствовать явно записанной текущей сетке после
исключения deleted cells. gridBefore/After и span оставшихся ячеек учитываются;
удалённый span не заполняет сетку и не чинит её. Обычный vertical continuation
по-прежнему требует существующего origin в предыдущей retained row. Ненулевая
история и прежние свойства не переписывают current geometry. Deleted-cell subtree
полностью остаётся в исходном файле и участвует в whole-input preflight.

`TableRevision` содержит kind, anchor метки, owner_anchor свойств, subject_anchor
строки/ячейки. Нет author/date/id/text payload. Старые PhysicalTable/Row/Cell и
history DTO используются без изменения; catalog получает собственные profile/hash.
При ошибке не возвращаются ни таблицы, ни history, ни revisions. Вставленные строки
не объявляют весь текст вставленным: inline deletion и hidden-run rules независимы.

`ara.docx_analysis.visible_retained_tables` предоставляет
`build_retained_table_snapshot`, `map_retained_table_spans`, `map_retained_table_span`.
Фиксированный profile `docx-analysis/final-visible-retained-tables-v1` сохраняет
прежние Visible DTO и source-backed batch mapping. Metadata inserted_table_row/cell
привязана к метке; excluded deleted_table_cell охватывает всю исходную ячейку.
Nested table/style внутри удалённой ячейки не выбирается для анализа. Поддерживаемые
истории остаются excluded historical_table_properties/grid. Source XML не меняется.

Mapping всегда перестраивает original-source proof, даже для пустого batch. Изменение
только удалённого текста тоже меняет source SHA; старое замечание нельзя без проверки
перепривязать к новому файлу. Физические XML пути после удалённой ячейки не сдвигаются.
Один fresh retained catalog, MoveCatalog, StyleContext и style proof на весь batch.

RetainedTableLimits добавляет max_revisions к прежним ограничениям. Подсчитываются
все WordNS ins/del/cellIns/cellDel/cellMerge в main до DOM, включая истории, удалённые
и неизвестные ветви. Canonical manifest ограничен потоково. Не запускаются I/O, Word,
модель, SQL или приложение; сохранённые DOCX не принимают правки автоматически.

Ограничения: текущая row deletion не означает автоматического удаления её текста,
поэтому остаётся blocked; cellMerge/hMerge и неоднозначные/пустые retained rows также
не интерпретируются. Отсутствующая/несогласованная сетка не достраивается. Whole-main
MoveCatalog и unread package parts сохраняют прежние ограничения. Это opt-in reader,
не полная DOCX матрица, native Word parity или готовый application admission.
[Контракт](d03-17a2b3b2-contract.md), [результат](d03-17a2b3b2-result.md).
