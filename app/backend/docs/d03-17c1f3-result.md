# D03-17C1F3 — supervisor завершён в согласованных fixture-границах

3 ноября 2026, Astra с очень высоким усилием по прямой команде Никиты продолжать
самостоятельно без остановок для смены модели. Исходный freeze `c24c428`, WIP
`98724fe`, [уточнение схемы](d03-17c1f3-timeout-addendum.md) и новая приёмка
`3c2670f`. Этот результат заменяет pending-статус прежнего checkpoint.

Supervisor соединяет очередь, exact claim, heartbeat, отдельный процесс,
остановку, guarded publication и восстановление подтверждённого исхода.
Ошибки/потерянные ACK не запускают второе вычисление и не теряют прежний результат.
Late admission и local deadline корректно завершаются без выдуманного времени.
Новая V12 сохраняет basis тайм-аута; существующая wall-clock история остаётся
прежней. Downgrade с continuous history запрещён, включая конкурентную запись.

## Проверки

- Новая schema acceptance до source: ожидаемый red, V12 ещё отсутствовала.
- Целевой прогон: **90 passed, 23,58s** — все 65 исходных F3 cases, три edge checks
  и 22 дополнительные schema/timeout проверки, без исключений.
- **`bash scripts/check.sh`: 3706 passed, 41 skipped, 24 subtests passed,
  74 warnings, 454,44s, exit 0.** Ruff и форматирование прошли.
- 504 source/test/config hashes неизменны во время финального gate. Из 483
  файлов предшествующего baseline 479 побайтово прежние; четыре изменения ровно
  по addendum: ORM, expected DB version и подготовка двух исторических test files.
  Все их assertions сохранены. Все 65 F3 acceptance побайтово равны `c24c428`.
- Main `ara_dev` по-прежнему **V8 `0008_docx_edit_drafts`**, schema/counts равны
  предыдущему checkpoint; `ara_test` пуста, временных БД нет. PostgreSQL работает.

Логи: `.runtime/d03-17c1f3-timeout-{red,targeted}.log`,
`.runtime/d03-17c1f3-finish-full.log`; snapshot
`.runtime/d03-17c1f3-finish-runtime.json`. Ни main migration, ни публикации,
ни изменений runner/tasks/progress. Чужие README/spec/backlog/research/defense
правки сохранены вне нашего commit.

## Границы и продолжение

Это explicit fixture supervisor, не готовое desktop-приложение. Настоящий Mac
driver проверен с прежним opaque reply → invalid_result и cleanup; valid B1
success проверен с явно синтетическим PlatformPort. Windows native/VM crash/
suspend, реальная модель, production provisioning/boot recovery и Word rendering
остаются отдельными gates. 41 skip не являются доказательством Windows.

F3 вычтен один раз: самостоятельный остаток **25–40 циклов**, без работы
Ани/Артёма и внешних platform/release gates. Далее C2: вход модели, запрет
truncation, проверка пакета и bridge. Режим оставляем Astra по последней команде;
возврат на Sol не требуется для продолжения. Актуальный upstream `353cfee` прочитан
через доступный GitHub; его новые partial/pairwise поля не принимаются молча
за совместимый complete B1 result. Веса по актуальному README передаются отдельно.
