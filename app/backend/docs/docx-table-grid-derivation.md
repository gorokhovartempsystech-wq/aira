# Логическая сетка таблицы без выдуманных XML узлов

`ara.docx_analysis.grid_tables.read_grid_table_catalog` предоставляет отдельный
`docx-tables/current-resolved-grid-v1`. New GridTable сохраняет реальные anchor,
parent_cell_anchor, properties_anchor, original grid_anchor/grid_columns и rows;
добавлены grid_mode и column_count. При отсутствии tblGrid grid_anchor=None и
columns пусты. При расширении существующей сетки columns содержат только реально
записанные gridCol. Производным столбцам не приписывается ложный source address.

Для каждой retained row используются текущие gridSpan (по умолчанию1), before/after
и сохранённые source cells/vertical origins. Если все положительные ширины строк
равны размеру существующей сетки, mode explicit и прежние допустимые gaps сохраняются.
Если сетка отсутствует/пуста/короче, одинаковые ширины и before=after=0 позволяют
вывести logical column_count: mode inferred для отсутствующей или augmented для
существующей сетки. Не рассчитываются пиксели, высота/ширина и AutoFit rendering.

Неравные totals, declared grid шире строк, nonzero gaps при необходимом выводе,
невалидная текущая сетка, неверный vertical origin или unsupported table revisions
не превращаются в «починенный» документ: catalog blocked, без частичного набора
таблиц/history/revisions. Старые свойства и deleted cells не задают число столбцов.
Nested grids обрабатываются независимо. Файл и его оформление не переписываются.

GridTableLimits наследует прежние ограничения с exact type проверкой. Whole main
проходит прежний preflight, включая history/deleted/unknown branches. Logical span
counts ограничиваются до построения manifest; плотная матрица и synthetic column
nodes не создаются. Streaming canonical digest ограничен отдельным max_manifest_bytes.

`ara.docx_analysis.visible_grid_tables` предоставляет build_grid_table_snapshot и
map_grid_table_spans/span с прежними Visible DTO. Fixed profile:
`docx-analysis/final-visible-grid-tables-v1`. Present grid учитывается прежним
metadata table_grid; inferred/augmented grid — дополнительным derived_table_grid
на реальном table anchor. Оригинальные paragraph/cell flow anchors и source slices
сохраняются. Batch mapping заново строит whole-source proof один раз, включая пустой
batch; старые profiles, изменённый source и поддельный coverage не принимаются.

Поддержка нейтральных styles, current history, retained insertions/deletions, hidden
runs, comments policy и unread parts наследуется без расширения старых profiles.
Это отдельная opt-in функция. Ненулевые fallback gaps, unequal rows, сложные row/
merge/boundaries, весь DOCX, native Word parity и application admission пока не закрыты.
[Контракт и первичные источники](d03-17a2b3c1-contract.md),
[результат](d03-17a2b3c1-result.md).
