# D03-15B1 — курсор и выделение в истории DOCX

31 октября 2026. Реализован [контракт B1](d03-15b1-contract.md) на Sol 6.1 High. Новый pure EditorSession оборачивает неизменную DocxSession, связывая exact package history с paragraph caret/selection и affinity. История открытого документа поддерживает split/join, range edits, вставку/удаление и форматирование; UI/HTTP/БД не менялись.

Split возвращает caret в новый правый paragraph, join — на стык в левом. Undo/redo возвращают selection соответствующего frame, включая обратное выделение, с точным source anchor восстановленного пакета. Session revision остаётся монотонной, frame IDs не переиспользуются после branch; capture/no-op/save не создают позиции истории. Metadata вытесняется вместе с core и не хранит копии полных core/projection/packages. Наружные snapshots не разделяют изменяемое состояние с controller.

Мутации выполняются на shallow copy доверенной core с immutable state. После native operation проверяется after selection и готовится весь ответ; только затем одной заменой публикуется controller state. Ошибка after/reply/native exporter не требует rollback через undo и сохраняет все исходные стеки/bytes/курсоры. Revision проверяется первой. Типы и anchors строгие, ввод/ошибки без внешнего I/O/логирования текста.

## Проверки

Freeze **e944c65**, red **7 failed**, 0,12 секунды. Frozen acceptance не менялась. Targeted: **14 passed**, 0,16 секунды — семь frozen и семь дополнительных cases на range caret, failure capture/undo/redo/save reply, strict revision priority, state-budget metadata и table target.

Первый полный gate дал 1786 passed: обнаружено, что фиксированный pyproject testpaths не включает новую папку tests/docx_editor, поэтому семь own cases в этот прогон не вошли. По уточнению разрешённых путей добавлен переэкспорт четырёх test-функций/семи cases в tests/docx_session/test_editor_history.py. Assertions/fixtures/frozen tests и pyproject/scripts/старые проверки не менялись; отдельный прогон shim — 7 passed. Первое обращение full gate после этого остановилось на lint длинных import aliases; aliases исправлены без изменения functions/проверок.

Окончательный `bash scripts/check.sh`: **1793 passed, 24 subtests passed**, 68 предупреждений, **168,19 секунды**, exit 0. Ruff/format проходят. Логи .runtime/d03-15b1-red.log, d03-15b1-targeted.log, d03-15b1-full-check.log (первый), d03-15b1-full-check-final.log. Source после окончательного gate не менялся. Не выдавать первый прогон за полный набор B1.

QA на synthetic rich: capture heading offset 6/left → split → format Heading2 → полный undo/redo. Подтверждены точный исходный пакет/selection и position IDs 0→1→2→0→2. Итог побайтово совпал с уже отрендеренным D03-15A: SHA256 `1239ac34f1e975cc56e97698acfab2f747d75e1b97f759b3794f00db66114529`. Соответствующая единственная страница повторно осмотрена: styles/runs/lists/table/image/header/footer сохранены, обрезаний/наложений нет. Новый renderer не требовался при точном совпадении bytes; Microsoft Word отдельно не запускался. Контроль .runtime/d03-15b1-qa.json.

Baseline схемы/ревизии/счётчиков совпал; ara_test пуста, временных ara_check_* нет. PostgreSQL оставлен для продолжения. Секреты/архив/чужие dirty-файлы/runner/tasks/progress/dependencies не менялись, публикаций/сообщений не было.

## Продолжение

Это in-memory controller metadata, без frontend bindings и crash recovery. Affinity сохраняется; pending typing format/ввод в пустой paragraph и compound Enter-policy ещё требуют B2/последующих ограниченных операций. Следующий шаг — контракт Enter/join intents, одна публикация составного действия и проверка next-style/выхода из пустого списка. Работа продолжается автоматически на Sol 6.1 High.
