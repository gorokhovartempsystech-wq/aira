# D03-14 — разбиение и совместимая склейка DOCX

31 октября 2026. Реализован [контракт](d03-14-contract.md) на Sol 6.1 High, F05/F11. Новый pure package ara.docx_package.boundaries; старые source/tests/HTTP/БД не менялись.

SplitParagraph делит body paragraph по Unicode code-point offset, включая пустой текст и оба края. Сохраняются стили, level-0 list identity и inline formatting; разрезается только нужный run/t. Целые atoms/runs копируются, изменённый текст XML-экранируется с xml:space=preserve. Новый paragraph не дублирует paraId/textId/rsids исходника. TAB и мягкие Word breaks сохранены, zero-width nodes имеют определённую сторону.

JoinParagraphs объединяет соседние body paragraphs без добавленного разделителя. Совместимость проверяется по expanded structural signature pPr, включая прямое форматирование, без зависимости от prefix/порядка attributes. Heading+Normal/разные properties/list IDs отклоняются. Правые runs переносятся с сохранением namespace bindings, включая default namespace и локальное shadowing. Смешанные inline styles сохраняются. Меняется только выбранный main XML, остальные части/ZIP metadata точные.

Прежние protection/settings/signature/range/opaque gates сохраняются. Консервативный перечень properties/attributes предотвращает молчаливую потерю сложных элементов. Touched-node budget проверяется до копирования targets; namespace maps сохраняются только для выбранных p, а не отдельно для каждого run. Growing output собирается с инкрементальным бюджетом, чтобы перенос большого namespace context не создавал неограниченный результат до проверки лимита.

## Проверки

Freeze **a285ece**: два новых acceptance файла и статус подготовки в контракте. До freeze fixtures проверены прежним projector; исправлены путь к synthetic rich fixture и lint входов. После freeze acceptance не менялась. Red: **48 failed**, 0,38 секунды. Целевой итог: **55 passed**, 0,46 секунды — 48 frozen cases и 7 дополнительных namespace/amplification/empty nodes/limits/list/opaque diagnostics cases.

Общий `bash scripts/check.sh`: **1765 passed, 24 subtests passed**, 67 предупреждений, **170,13 секунды**, exit 0. Ruff/format проходят, предыдущие проверки не ослаблены/не пропущены. Логи .runtime/d03-14-red.log, d03-14-targeted.log, d03-14-full-check.log. Source после полного gate не менялся.

Визуальный QA: synthetic rich heading split → совместимый join, отдельно AIRA numbered-list split с bold run. Bundled runtime 26.1026.10807; три результата по одной странице, все страницы просмотрены целиком. Heading/выделения/списки, merged table, рисунок/ссылка и колонтитулы сохранены, нет обрезаний/наложений. Все 19 нетронутых rich parts побайтово прежние. Rich split: 48187 bytes, SHA256 `2b849cdbe8060d030f9396548b3946788766bb9790e912bd96d759530f22a72b`; join: 48131 bytes, `b91fc4595244571849a8c928603182e434415075125c12731fa40ea47f8920c2`; AIRA: 2984 bytes, `38d29381ebf596bd797ea8a8f20927689300024d8cbc55b3e79fca350de1afde`. Контроль .runtime/d03-14-qa/export-check.json. Microsoft Word отдельно не запускался.

Схема/ревизия/счётчики основной БД совпали с baseline, ara_test пуста, временных ara_check_* нет. PostgreSQL оставлен для следующего цикла. Секреты/архив пользователя/чужие dirty-файлы не использовались; runner/tasks/progress/квота не менялись, push не выполнялся.

## Ограничения и продолжение

Только body paragraphs, один primitive на source; без UI/клавиш, HTTP, истории или crash recovery. Сложные/защищённые объекты и несовместимые paragraph styles дают явный отказ. Split не применяет w:next: это политика будущего controller. Join(split) не обязан вернуть тот же ZIP hash; exact undo строится на snapshots.

По прямой команде Никиты работа продолжается автоматически. D03-15 разделяется на bounded subcycles: **D03-15A** — три новых вида операций в единой существующей DocxSession history; **D03-15B** — controller/selection/composite Enter-policy. Затем отдельный durable working-state цикл. Это уточнение порядка реализации исходного дизайна, не объявление controller готовым. Режим остаётся Sol 6.1 High.
