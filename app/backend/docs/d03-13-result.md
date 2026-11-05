# D03-13 — атомарные HTTP-команды абзацев и форматирования

31 октября 2026. Выполнен [контракт D03-13](d03-13-contract.md), F05/F11/F12. Режим Sol 6.1 High. Основной frontend Ани и проверочный workspace не менялись.

## Реализация

Один новый POST /docx-documents/{document_id}/paragraph-commands принимает structure batch (insert/delete) либо format batch (style/list) по точным исходным anchors и expected text. Неизменные pure API D03-11/D03-12 сохраняют оформление и проверяют свои границы. JSON и native DTO валидируются до storage, транспорт ограничен 2 MiB, Idempotency-Key обязателен. Успех содержит operation_id и строковую storage revision; свежие anchors читаются через /view. OpenAPI описывает виды команд и обязательный header. Default factory остаётся health-only.

Под прежними scoped project/document locks одна транзакция сохраняет пакет, hash, revision+1, timestamp и durable receipt. Использована существующая V8 docx_edit_receipts, без миграций. Namespaced fingerprint отделяет paragraph commands от прежнего text-edit. Тот же ключ/normalized body возвращает исходный receipt, даже после более поздней записи, без повторного применения и без отката latest. Другой body/вид операции с тем же ключом даёт 409; scope проверяется до replay. Original bytes/title/created_at сохраняются. Semantic no-op получает одну revision, а повтор — прежний receipt.

Commit/receipt fault откатывает оба изменения; потеря ACK после реального commit допускает безопасный повтор. Все проверки DOCX и работа с БД выполняются в worker thread. Ошибки безопасны и не содержат текста запроса/исключений; stale/text/CAS, unsupported, limits и storage errors различаются. Новый middleware задаёт no-store на обоих входах общего ledger (paragraph-commands/text-edit), включая ошибки/cross-kind conflict; прежние payload/status/validation text-edit не менялись.

## Приёмка

Подготовка **bf638da**: контракт, frozen acceptance и ровно одна новая строка в прежнем точном allowlist маршрутов. Прямая команда Никиты самостоятельно выполнять оставшиеся функции разрешает необходимое расширение API; прежние строки/assertions сохранены. Красный прогон: **34 failed**, 3 предупреждения, 4,13 секунды. Frozen acceptance после подготовки не менялась. После реализации исправлялся код no-store для ошибок, проверки не удалялись.

Целевая проверка новой HTTP-приёмки, прежнего edit retry, полного allowlist и новых stream/schema/import boundaries: **84 passed**, 5 предупреждений, **11,11 секунды**. Отдельно process replay/normalized defaults и MAX_REVISION/per-document keys: **2 passed**, 2 предупреждения, **1,05 секунды**. Inert import новых модулей проверен с запретом файлов, secrets/env lookup, сети, процессов, DB setup и логирования. Stream tests подтверждают остановку чтения на превышении лимита и безопасный отказ до storage.

Общий `bash scripts/check.sh`: **1710 passed, 24 subtests passed**, 70 предупреждений, **171,74 секунды**, exit 0. Ruff/format проходят; прежние проверки не пропускаются и не ослаблены. Логи .runtime/d03-13-red.log, d03-13-targeted.log, d03-13-durability.log, d03-13-full-check.log. Source после полного gate не менялся.

## Экспорт через настоящий HTTP API

В собственной disposable PostgreSQL БД импортирован synthetic AIRA source. Через HTTP вставлен абзац, удалена старая заметка (revision 2), заданы Title/Heading1/Heading2/native numbered list (revision 3). Повтор первой операции после второй вернул прежний receipt revision 2; скачивание осталось на revision 3. Original bytes и пять остальных parts точные, все шесть ожидаемых paragraphs сохранены. Собственная QA БД удалена.

Скачанный DOCX **3187 bytes**, SHA256 `085ef4bd294193c841b9210795a0125826a53f43b6836d85e7ff9201638deb58`. Bundled documents renderer 26.1026.10807 создал одну страницу: просмотрена целиком, иерархия/маркировка/отступы читаемы, обрезаний/наложений нет. Fixture создан bundled Python, roundtrip использует runtime приложения, рендер — bundled LibreOffice. QA .runtime/d03-13-qa/export-check.json и download.docx. Microsoft Word отдельно не запускался.

## Handoff и оставшиеся границы

[DOCX API для редактора](docx-editor-api.md) описывает endpoints, обязательные defaults форматирования, batch/retry/conflict, ревизии и ограничения для frontend. Документ локальный, сообщений команде не отправлялось. Наличие API не означает готовность frontend или всего DOCX-редактора.

Unsent structural batches/их recovery и undo stack UI пока не подключены. Прежний /draft остаётся single-span контрактом. Split/join, вставка по курсору с сохранением styled runs, каталог импортированных styles, многоуровневые списки и сложные Word elements требуют отдельных циклов. Real ML, лицензия и desktop distribution не включены в этот цикл.

Schema/revision/counts основной БД совпали с baseline, ara_test пуста, временных ara_check_* нет. Старые source, БД/миграции, dependencies, runner/tasks/progress/инструкции и чужие dirty-файлы сохранены, кроме явно предусмотренного подключения app.py/allowlist. Секреты и пользовательский архив не читались. Push/deploy не выполнялись.

После завершения серии PostgreSQL штатно остановлен: stopped (data preserved). Разрешённая Никитой остановка для повышения режима — перед проектированием D03-14 split/join и устойчивого структурного черновика: Astra 6 High для контракта/рисков, затем Sol 6.1 High для реализации. Причина — перенос styled runs и namespace bindings между paragraphs, правила paragraph/list properties и точный undo без потери исходного DOCX; D03-14 ещё не начат.
