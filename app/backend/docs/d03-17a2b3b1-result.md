# D03-17A2b3b1 — текущие свойства таблиц и mapping завершены

4 ноября2026. Freeze **399caa8**. Red **50 failed / 0.42s**, отсутствуют namespaces.
Initial targeted **50 passed / 0.30s**, без исправлений подготовки acceptance.
Review добавил три проверки: current nested tables и excluded history flows;
coverage budget включает истории; author/id/date не раскрываются в DTO/repr.
Регрессия всех старых/новых readers/catalogs **374 passed / 2.13s**.

CurrentTableCatalog + отдельный current-property visible profile реализованы без
копирования/изменения исходного XML; четыре kinds истории, точные source anchors,
whole-input preflight, current geometry/style и source-backed batch mapping.
Три заранее разрешённых private shared extensions; старые main acceptance/contract
неизменны. Ruff712 files green;763 final hashes,747 previous unchanged.
Полный обязательный `bash scripts/check.sh`: **5250 passed, 45 skipped,
78 warnings, 24 subtests passed / 795.77s, exit0**. Повторных прогонов и ослабления
проверок не потребовалось. Контрольные суммы всех763 файлов совпали; из750 прежних
747 неизменны, ровно три заранее разрешённых shared source changes. Main readonly
snapshot совпал с a4: V8 `0008_docx_edit_drafts`, schema/counts без изменений,
ara_test пустая, временных ara_check БД нет. Source/тесты/контракт не менялись во
время полного gate. ML/SQL/API/deps/runner/tasks/progress/архив/чужие файлы untouched.

[Руководство](docx-current-table-properties.md). Новые namespaces current_tables и
visible_current_tables дают отдельный opt-in profile; исходный файл не принимает
и не отклоняет правки Word. Native Word parity, application admission и полноценная
матрица DOCX остаются незавершёнными. Current row/cell revisions, сложные merge/
boundary и ненейтральные стили не выдаются за разобранные.

Следующий отдельный цикл **D03-17A2b3b2**: retained table grid/text/mapping для
добавленных строк/ячеек и удалённых ячеек при явной согласованной текущей сетке.
Текущие row deletion и cellMerge остаются отдельной задачей доказательства topology.

