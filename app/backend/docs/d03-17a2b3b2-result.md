# D03-17A2b3b2 — retained table revisions/text/mapping завершены

4 ноября2026. Freeze **4557d1c**; red **38 failed / 0.32s**, namespaces отсутствуют.
Initial targeted **38 passed / 0.27s**, без test setup corrections. Review добавил4
проверки: retained vertical origin вокруг deleted siblings; duplicate/conflicting
row markers; deleted-cell envelope; coverage budget. Main acceptance/contract unchanged.
Combined old/new readers/catalogs **416 passed / 2.23s**, Ruff724 files green.

Retained table catalog и versioned visible text/mapping реализованы отдельными
namespaces без изменений старого source. Inserted row/cell и deleted cell имеют
точные source anchors; исключение ячейки не меняет XML или индексы. Current grid
должен точно совпасть с retained row widths; unknown row/merge topology blocked.
776 final hashes, все763 прежних файлов неизменны. Обязательный `bash scripts/check.sh`: **5292 passed, 45 skipped, 77 warnings,
24 subtests passed / 787.87s, exit0**. Повторный прогон не потребовался.
776 final hashes совпали; все763 предыдущих файла неизменны. Frozen contract/main
acceptance сохранились; own edge test получил только59 строк новых проверок.
Main readonly snapshot совпал с b3b1: V8 `0008_docx_edit_drafts`, schema/counts
не изменились, ara_test пустая, временных ara_check БД нет. Во время full gate
source/tests/frozen contract не менялись. ML/SQL/API/deps/runner/tasks/progress/архив
и чужие изменения untouched.

[Руководство](docx-retained-table-revisions.md). Это отдельная pure opt-in возможность,
не application admission или полная DOCX матрица. Native Word/Windows gates остаются,
current row deletion/cellMerge/hMerge и неоднозначные границы не объявляются готовыми.
Следующий цикл **D03-17A2b3c1**: вывод логического числа столбцов из согласованных
current retained rows при отсутствующей/пустой/недостаточной сетке; без выдуманных
исходных адресов и без расчёта пиксельного оформления. Остальные DOCX блоки дальше.

