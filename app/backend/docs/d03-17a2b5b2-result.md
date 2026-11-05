# D03-17A2b5b2 — verified original table controls

5 ноября 2026. Baseline `00a7492`, freeze `e55da8a`. Red: **48 failed /0.46s**.
Первый targeted: 46 passed /2 failed /0.38s. Найдена ошибка реализации: промежуточные
parent constructors индексировали прежний table proof; финальные history/revision
индексы нового reader теперь строятся по свежему доказанному catalog. Тесты не менялись.
После исправления 48 passed /0.34s; review добавил 6 случаев: однократный учёт controls,
сноски в controlled cell, эквивалентность uncontrolled fields, deleted payload proof,
gap inference refusal, foreign namespace. Targeted **54 passed /0.38s**;
combined readers/catalogs **646 passed /3.14s**. Ruff/format — 795 файлов.
855 финальных хешей; 843 из прежних 847 unchanged, четыре разрешённых private hooks.
Frozen main/contract exact; frozen edge prefix preserved, только review additions.
Setup corrections не потребовались.

Новый профиль final-visible-control-tables-v1 читает rich controls вокруг таблиц,
строк, ячеек и блоков внутри ячеек. Физические XML-родители и логические родители
таблицы учитываются отдельно, source paths не меняются. Каждая wrapped row/cell
остаётся одним настоящим элементом; empty wrappers не создают структурных объектов.
Свойства и grid требуют прежнего физического положения, пустые controls не могут
исправить неправильный порядок. Grid spans/vertical merges/current histories,
retained cell revisions и neutral table styles проверяются прежними алгоритмами.

Новый проход по таблице использует только реальные узлы из свежего table proof,
сохраняет точные cell flows/nested tables/story ownership, включая notes/header.
Control properties проверяются один раз; every control boundary, включая empty,
остаётся field barrier. Unknown retained payload и неоднозначная сетка блокируют
весь snapshot. Общий pipeline/preflight/source-backed batch mapper переиспользуется;
старые публичные readers/catalogs сохраняют свои профили и границы.

Full `bash scripts/check.sh`: **5688 passed, 45 skipped, 78 warnings, 24 subtests passed /796.80s**, exit0. Все 855 финальных хешей совпали; 843 прежних файла вне четырёх разрешённых hooks неизменны. Readonly snapshot основной V8 `0008_docx_edit_drafts` совпал с b5b1: схема, revision и counts, содержимое строк не читалось. Выборочный локальный commit; внешняя публикация не выполнялась. Это pure reader, не готовый application admission,
редактор сложного DOCX или native Word layout. Plain/bound/placeholder/other control
типы, MC, media/numbering/сложные revisions и native Windows/Word остаются gates.
После фиксации продолжаем отдельный bounded цикл оставшейся DOCX матрицы.
