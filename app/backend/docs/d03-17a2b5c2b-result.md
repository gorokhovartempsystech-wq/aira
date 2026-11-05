# D03-17A2b5c2b — coherent selected metadata contexts

5 ноября 2026. Baseline `d711d22`, frozen contract/acceptance `8db5427`.
Red **34 failed /0.39s**; первый targeted **34 passed /0.42s**.
Review добавил семь проверок: foreign-namespace body, external styles link,
missing base style, discarded invalid settings, unused settings raw quota,
compatibility action/item budgets и wrong note relationship kind.
После review **41 passed /0.46s**; широкая регрессия прежних readers/catalogs
**867 passed /4.37s**. Подготовка зафиксированных тестов не исправлялась.

Новая фабрика строит один immutable view и читает из него styles, table-style
proof, sections/settings и note definitions. Все адреса остаются исходными;
профили выбранной семантики отдельно версионированы. Blocked view/catalog
атомарно убирает все четыре контекста. Per-style unresolved records не
подменяются разрешением анализа. Logical root содержит ровно один Word body
того же namespace. Aggregate raw quotas действуют до DOM, включая unused и
ambiguous styles/settings; весь bundle ограничен streaming manifest budget.

Восемь разрешённых private hooks сохраняют прежние public API/default behavior.
Все 864 прежних контрольных файла вне этих hooks совпадают с baseline.
Новый whole-story reader/mapping и application admission ещё не подключены.

Full `bash scripts/check.sh`: **5827 passed, 45 skipped, 80 warnings,
24 subtests passed /797.80s**; Ruff/format818 files. Все 881 frozen hashes
совпали после полного прогона. Readonly основная V8 `0008_docx_edit_drafts`:
schema/revision/counts совпали с C2A, содержимое строк не читалось.
Выборочный локальный commit, без публикации.

Далее D03-17A2b5c2c: whole-story snapshot и mapping через те же selected contexts,
с исходными anchors для таблиц, перемещений и сносок. Native Word/Windows,
media/сложный редактор/export и внешние UI/ML/release gates остаются.
