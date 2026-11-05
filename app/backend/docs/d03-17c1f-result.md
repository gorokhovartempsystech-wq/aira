# D03-17C1F — результат проектирования supervisor

3 ноября 2026, Astra 6 High, после E4 `b650ffa`. Подготовлены [проект](d03-17c1f-design.md) и [контракт первого цикла](d03-17c1f1-contract.md). Поведение приложения не менялось, source/acceptance/migration C1F ещё отсутствуют. Это техническое проектирование уже согласованного управления проверкой, не готовый production runtime.

Выбраны один dispatcher для готового C1A и отдельные bounded jobs для SQL/процессов. Определены разные исходы потери ответа: недоставленный permit можно отозвать до SQL; принятый permit и неизвестный COMMIT требуют reconciliation. Stop не удаляет уже записанный успех. Scoped exact claim не использует старый глобальный поиск очереди; heartbeat receipt содержит время из той же SQL transaction. Enqueue deadline не переякоряется после replay/restart.

Durable ledger записывается до любого create. Физическое завершение и собственная очистка позволяют сохранить drained; лишь после SQL reconciliation допускается clean и следующий запуск. Armed после crash без доказательства завершения остаётся quarantine. Free slot, SQL terminal, истёкшая lease и слова о перезагрузке fence не снимают. Verified boot provider пока отсутствует: автоматическое восстановление этой редкой ветки и production provisioning остаются открытым native/desktop release gate. Это ограничение доступности явно сохранено, не представлено как готовая функция.

Три последовательных implementation цикла на **Sol 6.1 High**:

1. **D03-17C1F1** — dispatcher, Stop/lease mailboxes и bounded PublicationPort; без SQL и запуска процессов.
2. **D03-17C1F2** — точный контракт новой V11, scoped SQL receipts, durable ledger и recovery services на одноразовых БД.
3. **D03-17C1F3** — явный supervisor start/shutdown, Mac/Windows adapters, ограниченные jobs и композиционные crash tests.

У каждого своя acceptance/freeze/red/targeted/full/result/local commit. F2/F3 требуют подготовки собственных точных контрактов в выбранных границах; повторный Astra pass только при новом архитектурном противоречии. Existing native fixture reply не соответствует B1: portable SQL success проверяется отдельным честным fixture port, native opaque reply должен отклоняться. Реальный мост/weights — C2; frontend Ани не заменяется.

## Проверка и сохранность

`bash scripts/check.sh`: **3508 passed +24 subtests,41 skipped,77 warnings,396,22s,exit0**. Ruff/format437files прошли. Лог `.runtime/d03-17c1f-design-full-check.log`. Это регрессия существующего кода, не тест ещё не реализованного C1F; искусственный red для docs-only дизайна не создавался. Native skips остаются открытыми gates.

Стартовые468 source/test/config hashes совпали с E4 baseline; промежуточная и **финальная** проверки также без изменений. Read-only снимки schema/revision/counts до/после gate совпали между собой и с финальным E4: `ara_dev` V8 `0008_docx_edit_drafts`, `ara_test` пуста, временных БД нет. Файлы `.runtime/d03-17c1f-design-{start,final}-{hashes,runtime}.json`. PostgreSQL оставлен работающим; содержимое пользовательских документов не читалось. UTF-8/все относительные ссылки семи собственных документов и `git diff --check` проверены.

Дополнительно read-only проверены локальные PG18.6, fsync/full_page_writes/synchronous_commit=on, psycopg3.3.5/libpq180006, SQLAlchemy2.0.54. Семантика durability/timeouts сверена с официальной PostgreSQL18 документацией; ссылки в проекте. Это наблюдение dev окружения, а не обещание о будущей поставке.

Собственные изменения: эти три новых design/contract/result документа и статус/ссылки в C1, C1E, C1F preflight, development queue. Чужие README/backlog/spec/research/defense изменения, `.artifact-build/` и `output/` сохранены. Архив/секреты не читались; source/tests/рабочая БД/dependencies/runner/tasks/progress не менялись. Нет push/публикации или production startup.

## Передача

**Вернуться на Sol 6.1 High и начать D03-17C1F1**, с новой независимой приёмки перед source. На той же модели продолжать F2/F3 после законченных проверенных циклов. Предыдущую E4 acceptance повторно не переписывать.

Самостоятельный остаток **28–43 цикла**. Прежняя одна строка C1F стала тремя (+2 к26–41), без новых продуктовых функций; design завершён, реализация этих трёх ещё не вычитается. Оценка включает остальные DOCX readers/editing gaps, результаты/адаптер, лицензирование, поставку и финальную интеграцию; не гарантированный потолок и не готовность релиза без frontend/weights/целевых платформ.
