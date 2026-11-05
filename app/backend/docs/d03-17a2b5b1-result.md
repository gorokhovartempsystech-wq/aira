# D03-17A2b5b1 — completed in available reader scope

4–5 ноября 2026. Baseline `207880e`, freeze `8422ace`. Red: **55 failed / 0.45s**.
Первый targeted: 54 passed /1 failed /0.30s; положительная fixture имела две grid
колонки при одной ячейке. Подготовка трёх новых одноколоночных fixtures исправлена:
positive inline-cell и два negative wrapped-table/cell-control. Assertions unchanged,
как явно разрешено frozen contract; setup-only commit `3309b03`. После исправления:
55 passed /0.28s. Review добавил 6 тестов: максимальная вложенность, пустой control
как field barrier, hyperlink nesting, чужой Word namespace, hidden placeholder gate,
byte-preserving mapping. Targeted **61 passed /0.30s**; combined readers/catalogs
**592 passed /2.81s**. Ruff/format — 788 файлов. 847 финальных хешей, все 839 прежних
unchanged, frozen assertions и original edge prefix сохранены.

Новый профиль final-visible-rich-controls-v1 читает сохранённый текст unbound rich
SDT: абзацы/вложенные block controls в main/header/footer/notes, inline controls
в обычных абзацах и в уже доказанных ячейках таблиц. Сохраняются оригинальные пути
и контекст; XML не переписывается, wrapper не становится fake paragraph/run.
Настройки будущего ввода и delimiter не переопределяют visibility сохранённых runs.
Пустые controls не выдумывают текст; закрытые поля внутри работают, пересечение
границы control незакрытым field явно блокируется. Note markers и source slices
сохраняют прежний смысл. Raw count/depth controls +fields проверяются до DOM,
включая unused/deleted/history branches. Старый код и профили не изменены.

Полный `bash scripts/check.sh`: **5634 passed, 45 skipped, 80 warnings,
24 subtests passed / 799.52s**, exit 0; Ruff/format 788 файлов. Все 847 финальных
хешей неизменны после прогона; все 839 прежних unchanged. Readonly snapshot schema/
counts/revision совпал с b5a1: main V8 `0008_docx_edit_drafts`; строки документов
не читались/не менялись. 45 skips — прежние native/platform gates. Локальная фиксация
включает только файлы этого цикла; посторонние изменения сохранены.
 Это pure reader, не application admission или
готовый редактор всех элементов Word. Bound/placeholder/plain/date/other controls,
таблицы и cell/row wrappers внутри SDT, MC, сложные revisions/section contexts,
media/numbering и native Word/Windows остаются отдельными gates. Следующий bounded
цикл D03-17A2b5b2 расширит чтение rich controls вокруг таблиц с сохранением физических адресов.
