# D03-17A2b3a4 — чтение таблиц с нейтральными стилями завершено

4 ноября 2026. Freeze **6ee235b**; red **40 failed / 0.39s** (namespace отсутствует).
Initial targeted **40 passed / 0.29s**, без исправлений подготовки тестов. Review
добавил две проверки: нейтральный стиль не обходит hidden-row/implicit-character
ограничения; одинаковые цитаты в разных таблицах сохраняют разные source slices.
Основная frozen acceptance и контракт неизменны. Combined readers/catalogs:
**321 passed / 1.85s**.

Реализован отдельный profile `docx-analysis/final-visible-neutral-tables-v1`:
выбор собственного explicit/default table style, proof всех ancestors/conditional
regions, cnfStyle metadata и source-backed batch mapping. Три разрешённых private
shared extensions сохраняют прежние profiles/DTO/guards. Подробности —
[руководство](docx-visible-styled-tables.md) и [контракт](d03-17a2b3a4-contract.md).

Первый полный gate: **5196 passed, 45 skipped, 80 warnings, 1 error, 24 subtests**,
797.72s. Ошибка подготовки старого `test_invalid_hide_locator_never_mutates_state`
возникла при polling анализа: HTTP503 storage_unavailable. Точная первопричина
не установлена; общий журнал PostgreSQL не позволяет привязать её к конкретному
запросу. Без изменения source/tests весь проблемный модуль прошёл **40/40 / 34.18s**.
Повторный обязательный `bash scripts/check.sh`: **5197 passed, 45 skipped,
81 warnings, 24 subtests passed / 815.48s, exit0**. Не считать разовую 503 исправленной
или доказывать её связь с новым pure reader; при повторении нужен отдельный
воспроизводимый runtime investigation. Оба журнала сохранены в ignored `.runtime`.

Ruff/check/format: 700 files, exit0. **750 final hashes** совпали; из 743 прежних
файлов **740 неизменны**, ровно три заранее разрешённых shared source changes.
Read-only main snapshot совпадает с предыдущим: V8 `0008_docx_edit_drafts`, схема и
counts без изменений, ara_test пустая, временных ara_check БД нет. Документы и секреты
не читались. ML/SQL/API/deps/runner/tasks/progress/старые тесты не менялись.

Это проверенная opt-in библиотечная функция, не готовность полноценного DOCX или
приложения. Ненейтральные стили, tracked table history/revisions, numbering/settings/
stories/fields/MC, native Word/Windows и подключение к application остаются gates.
Далее отдельный **D03-17A2b3b1**: текущие свойства таблиц при сохранённой истории Word,
структурный каталог и его текст/mapping в одном функциональном цикле.
