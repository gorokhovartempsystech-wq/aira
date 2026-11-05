# D03-17C1F3 — результат проектирования

3 ноября 2026, Astra6 High, после F2 `3fc77f2` и preflight `e9a6209`. Подготовлены [точный контракт](d03-17c1f3-contract.md) и [независимая матрица приёмки](d03-17c1f3-acceptance.md). Поведение приложения пока не меняется: source/acceptance F3 ещё не создавались.

Local timeout теперь имеет определённый путь в SQL: first Stop reason/original deadline → private generation seal → проверка отсутствия неизвестной публикации → issued exit authority → scoped terminal transaction. Пока COMMIT неизвестен, сохраняются прежний publisher/token и выполняется C1B reconciliation; подтверждённый success не затирается. Terminal status и physical cleanup имеют отдельные полномочия, поэтому timed_out не разрешает преждевременно запустить следующую модель.

Отдельно разрешена гонка потерянного ACK settlement: exact pending outcome сначала подтверждается F1. Если он уже resolved, publisher закрывается для дальнейших вызовов, а SQL проверяется новым ordered read barrier/source-backed restore. Это сохраняет неизменный rolled_back token даже когда reaper уже завершил run, без конфликтного повторного terminal settlement и без изменения C1A/B/F1.

Зафиксированы explicit fixture API, пять постоянных job lanes/один coordinator, wake+servicing≤5ms для прежнего port50ms, original admission anchors, bounded queue/retention, read barriers неизвестных ACK, capture-before-close и Mac/Windows adapters. Release False не повторяет инвалидированный slot; persisted armed после crash остаётся quarantine. Production provisioning/verified boot recovery и запуск реальной модели не объявлены решёнными.

## Проверка дизайна

`bash scripts/check.sh`: **3616 passed +24 subtests,41 skipped,75 warnings,397,42s,exit0**. Ruff/format452files прошли. Лог `.runtime/d03-17c1f3-design-full-check.log`. Это регрессия существующего приложения, не проверка ещё не реализованного F3:57 новых сценариев пока только спроектированы. Artificial red для docs-only дизайна не создавался; freeze/red будущей реализации не заявлены выполненными.

Read-only schema/revision/count snapshots до/после gate совпали с F2 final baseline: `ara_dev` **V8 `0008_docx_edit_drafts`**, `ara_test` пуста, временных БД0. Все **483 source/test/config hashes** совпали до/после. Доказательства `.runtime/d03-17c1f3-design-{start,final}-{runtime,hashes}.json`; финальный снимок снят строго после завершения тестов, без параллельных временных БД. PostgreSQL оставлен работающим; содержимое пользовательских документов/секреты не читалось.

Проверены UTF-8, относительные ссылки и таблицы новых документов, `git diff --check`. Собственные изменения — три новых F3 contract/acceptance/design-result документа и текущие статусы в F3 preflight/C1F design/development queue. Чужие README/backlog/spec/defense/research изменения сохранены; `.artifact-build/`, `output/` и архив не читались. Нет изменений source/tests/migrations/runner/tasks/progress, push или production startup.

## Передача

**Вернуться на Sol6.1 High для реализации D03-17C1F3.** Сначала вся новая independent acceptance по матрице и freeze/red, затем checkpoints: jobs/authority/SQL/port → portable coordinator с настоящим PostgreSQL → native adapters/доступные gates. Каждый checkpoint проверяется, весь F3 закрывается только после итогового full gate/сохранности/result/local commit. Старые source/tests/DDL/runner/tasks/progress не изменять.

Остаток самостоятельной работы **26–41 цикла**: F3 всё ещё предстоит реализовать; это уточнение уже учтённого этапа, новых ID/функций нет. Диапазон включает остальную backend/DOCX/лицензию/поставку и финальную интеграцию; готовность релиза зависит также от frontend Ани, модели Артёма и целевых native/Word/installer проверок.
