# Каталог физической сетки таблиц

`ara.docx_analysis.tables.read_table_catalog(data, source_sha256=...)` строит
неизменяемые source-bound records по исходному DOCX. Профиль
`docx-tables/main-physical-grid-v1` описывает прямую текущую структуру main part,
не итоговый текст, стили, видимость, разбиение по страницам или разрешённые правки.

Catalog содержит таблицы в XML preorder, строки и physical cells, column start/span,
vertical merge origin, исходные properties/grid anchors и ordered paragraph/table
blocks каждой ячейки. Вложенные таблицы имеют parent_cell_anchor. Продолжение
объединения содержит свои blocks, а не повторяет blocks origin; никакой текст при
индексации не удаляется и не копируется. Reader обязан отдельно решить final view.

Status indexed означает только распознанную direct-current сетку. absent относится
только к relevant main markup, blocked возвращает пустой tables tuple и один fixed
issue. У catalog нет complete. Unknown styles/hidden properties/paragraph contents
ещё не прочитаны; другие parts не учтены. Snapshot для ML/редактора не заменяется им.

Первый профиль требует явную tblGrid и согласованную ширину строк, допускает
horizontal gridSpan, before/after gaps, aligned vertical merges и nested tables.
Implicit/augmented/conflicting grids возвращают unresolved_table_grid: формат Word
иногда позволяет восстановление сетки, но этот reader его пока не выполняет.
Legacy hMerge/table revision structures и unknown wrappers пока blocked.
Inline ins/del не приравниваются к добавлению/удалению строки.

SourceAnchor хранит точный SHA, main-part path и zero-based element child indices;
comments/PIs не влияют на них. API не читает файлы, сеть, окружение, SQL или Word.
Caller передаёт exact bytes и их SHA. Technical TableLimits ограничивают XML до DOM,
включая namespaces/excluded branches; geometry/output также bounded, dense grid не
строится. Digest проверяет согласованность, не подлинность внешнего DTO: будущий
reader должен заново получить catalog из исходника.

Старые visible_main/visible_moves по-прежнему блокируют таблицы. Следующий b3a2
должен добавить final table flows с отдельным profile, source mapping, continuation
checks, style/visibility accounting и полным coverage. Native Word/layout parity,
редактирование сложных таблиц и application admission — отдельные gates.
