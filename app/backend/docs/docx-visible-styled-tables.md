# Итоговый текст таблиц с нейтральными стилями

`ara.docx_analysis.visible_styled_tables` предоставляет отдельные
`build_styled_table_snapshot`, `map_styled_table_spans` и `map_styled_table_span`.
Аргументы и immutable Visible* DTO такие же, как у [простых таблиц](docx-visible-tables.md),
но фиксированный profile — `docx-analysis/final-visible-neutral-tables-v1`.
Старые profiles не расширены; mappers взаимно отвергают чужой snapshot, включая
перехешированный объект и пустой batch.

Перед чтением каждой таблицы выбирается её прямой tblStyle либо default для типа
`table` из того же styles part. Строки TableNormal/TableGrid не зашиты в код. Вложенная
таблица выбирает собственный style/default. Выбранное определение должно пройти
[proof нейтральности](docx-table-styles.md): every ancestor/conditional region содержит
только известные свойства оформления. Незадействованные неразрешённые стили не
подставляются автоматически. Missing/wrong-kind/неразрешённый выбранный стиль
блокирует весь main flow; direct vanish=false не обходит эту проверку.

Служебные cnfStyle под pPr/trPr/tcPr учитываются как metadata после доказательства
нейтральности всех возможных областей. Проверяются точный набор атрибутов, 12-битный
val и boolean flags; неизвестные свойства или содержимое не игнорируются. Direct
band sizes учитываются как оформление. Их интерпретация не меняет состав текста,
поскольку все условные branches выбранного style уже проверены.

Paragraph/character/direct hidden, границы абзацев, комментарии и revisions сохраняют
прежние правила. Свойство hidden у строки по-прежнему не становится UI metadata.
Порядок body/cell/nested paragraphs, физические flow anchors и исходные slices
не зависят от выбранного имени стиля; SHA исходника и profile входят в fragment ID.
Даже изменение только styles invalidates старый snapshot при обратном отображении.

При batch mapping один раз перестраиваются TableCatalog, MoveCatalog, StyleContext
и style proof из исходных bytes. Отдельный styles preflight включает namespace URI и
непрочитанные branches до semantic DOM. В новом reader private proof использует
тот же свежий StyleContext, не повторно читает его для каждого замечания/ячейки.
Публичного аргумента для передачи доверенного caller proof нет.

Это opt-in библиотечный reader, не полнота DOCX и не application/ML admission.
Ненейтральные стили, сложные tracked table changes, stories/fields/numbering/settings,
native Word parity и frontend остаются отдельными задачами.
[Точный контракт и первичные источники](d03-17a2b3a4-contract.md).
