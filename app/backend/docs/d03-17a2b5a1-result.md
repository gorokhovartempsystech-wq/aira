# D03-17A2b5a1 — completed in available reader scope

4 ноября 2026. Baseline `c733fd2`, freeze `4905ea2`. Red: 40 failed / 0.37s;
первый целевой прогон 40 passed / 0.26s. Setup corrections не потребовались.
Review добавил 5 случаев: несколько абзацев внутри одной ячейки, пустая инструкция
с буквальным cache, удалённое dirty field, note label внутри сохранённого результата
и запрет pairing main/header. Combined readers/catalogs: **483 passed / 2.68s**.
Ruff/format — 781 файл. 839 финальных хешей; 828 из прежних 831 unchanged, только
три разрешённых private reuse hooks в visible_notes. Frozen contract/main tests
не изменились, edge содержит только review additions.

Новый профиль final-visible-field-results-v1 читает сохранённые результаты fldSimple
и закрытых complex fields, включая вложенные поля и переходы между абзацами одного
flow. Инструкции не исполняются; instrText вне code region — обычный исходный текст.
Hidden markers участвуют в структуре до run visibility, hidden result остаётся скрытым.
Правки/истории/notes/tables сохраняют прежние границы; code content не активирует сноски.
Empty simple и code-only closed complex не выдумывают символов. Межъячеечные, section,
story и crossed-wrapper структуры блокируют весь snapshot. True dirty остаётся явным
ограничением; обновление полей и native layout не выполняются.

Общий pipeline переиспользуется без копирования: private reader/profile/preflight hooks
с прежними defaults. Перед любым DOM действует дополнительный счётчик полей, включая
excluded/unused части. State machine проходит original plans один раз и ограничивает
глубину; публичных fake runs/paragraphs нет. Source-backed batch mapping сверяет новый
профиль с исходником, сохраняет code-point slices и note-reference context.

Полный `bash scripts/check.sh`: **5573 passed, 45 skipped, 82 warnings,
24 subtests passed / 799.66s**, exit 0. Ruff/format: 781 файл. Все 839 финальных
хешей после прогона unchanged; прежние 828 вне трёх разрешённых hooks unchanged.
Readonly schema/count snapshot совпал с b4b2: main V8 `0008_docx_edit_drafts`,
содержимое пользовательских документов не читалось и не изменялось. 45 skips —
сохраняющиеся platform/native gates, не подтверждённая Windows/Word приёмка.
Локальная фиксация включает только файлы этого цикла; посторонние изменения сохранены.
 Это pure reader, не application admission,
редактор, расчёт свежих field values или полная обработка DOCX. Dirty/form fields,
malformed fallback, MC/SDT/textboxes/media/numbering/сложные revisions и native Word/
Windows остаются отдельными gates. Далее — D03-17A2b5b1: saved rich-text content controls
в отдельном ограниченном цикле, без изменения продуктового scope.
