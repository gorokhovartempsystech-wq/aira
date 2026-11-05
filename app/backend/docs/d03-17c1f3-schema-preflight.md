# D03-17C1F3 — конфликт local timeout со схемой V11

**Актуальный итог, 3 ноября: D03-17C1F3 завершён в fixture-границах.** [Результат](d03-17c1f3-result.md):90 targeted; полный gate3706passed/41skipped/+24subtests,exit0; main V8 неизменна. Конфликт early timeout устранён additive V12 с сохранением истории и безопасным downgrade. По последней команде Никиты продолжаем на Astra без смены режима: далее C2. Самостоятельный остаток **25–40**; нижние pending-статусы исторические.

3 ноября 2026, реализация на Sol6.1 High после дизайна `ddd4458`. Independent acceptance заморожена **c24c428**:65 cases, red30failed/35errors на отсутствии F3. Synthetic reply отдельно прошёл реальный B1/B2 codec. Старые source/tests/schema не менялись.

## Подтверждённое противоречие

[Контракт F3 §6.2](d03-17c1f3-contract.md) требует terminal `timed_out / deadline_exceeded` по continuous deadline раньше SQL wall deadline, сохраняя `finished_at=max(SQL now,created_at)` и неизменный `deadline_at`. При этом F3 разрешает только новые supervisor modules, без ORM/migrations/DDL и изменений F2.

Но `docx_analysis_runs` уже имеет **ck_dar_terminal_reason**:

```sql
status = 'timed_out'
AND error_code = 'deadline_exceeded'
AND finished_at >= deadline_at
```

Полное условие также сохраняет отдельные guards failed/cancelled. Источники: `src/ara/models.py`, строки671–675, migration `0010_docx_analysis_storage.py`, строки188–197; V11 наследует это ограничение. Оно не проверяет C1A/local clock и не делает исключения для выданного ExitAuthority.

На новой synthetic V11 воспроизведён обычный queued→timed_out с SQL now раньше deadline: PostgreSQL отверг его именно по этому constraint; transaction rollback оставил прежние status/finished/deadline. Probe **1passed**, `.runtime/d03-17c1f3-schema-boundary.log`, стенд `.runtime/test_f3_schema_boundary.py`. Рабочая БД не использовалась.

Основная frozen acceptance также обнаружила конфликт в первом active-deadline case: RAM/native Stop сработал, early terminal SQL отвергнут, run не получил выдуманный успех/отмену. Последующие попытки остаются pending/fail-closed. Существующий код не подставляет будущее finished_at, не меняет deadline и не снимает constraint. Это **пробел предшествующего дизайна**, не ошибка входного Word, лицензии Microsoft, тестового SQL splitter или доступа к socket.

## Проверенная часть реализации

Первый foundation checkpoint:9passed. Финальная доступная композиция — **64passed/4deselected,19,35s**:61 независимая проверка и3 собственные edge checks. Лог `.runtime/d03-17c1f3-checkpoint-final-targeted.log`; предыдущие63passed сохранены отдельно. Четыре исключения относятся только к диагностическому прогону доступной части; frozen tests/assertions/критерии не менялись, F3 не объявлен завершённым:

1. local D активной попытки раньше SQL deadline;
2. D во время admission, затем late enqueue;
3. local D после взятого permit и доказанного rollback;
4. поздний claim ACK после original D.

В доступной части проверены bounded lanes/queue, неизменные anchors, exact claim/arm, потерянные commit ACK, stable settlement, Stop, startup/drained recovery, shutdown retention, no second create, source-backed SQL success на synthetic port. На настоящем macOS driver opaque reply корректно отклонён как invalid_result и cleanup завершён; также проверен immediate Stop. Portable driver-shaped Windows wiring не является native Windows evidence. Натуральное завершение не прекращает последующие SQL heartbeat во время долгой валидации, job errors не экспортируют произвольный exception code. Уже зарегистрированный key возвращает тот же ticket даже при blocked/unknown enqueue и сбое clock, без нового anchor/provider.

Обязательный финальный `bash scripts/check.sh` выполнен **без исключения этих четырёх cases**:1failed/3650passed/41skipped/34errors,+24subtests,exit1. Primary failure — active early deadline; незавершённый S блокирует последующие новые F3 setups. Прежние3616tests+24subtests прошли, никаких прежних failures/errors. [Подробный checkpoint result](d03-17c1f3-checkpoint-result.md). Green64 — не полный gate и не завершённый F3. Main V8/schema/counts и502 gate hashes неизменны.

## Следующий focused design — Astra6 High

Нужна узкая корректировка **технического контракта**, без новых продуктовых функций/ID:

- выбрать durable представление continuous timeout, совместимое с сохранностью прежней wall-clock истории и честным finished_at;
- определить additive schema change/ORM/точный DDL и пределы upgrade/downgrade; ранние terminal records нельзя уничтожать ради downgrade;
- учесть frozen F2 `database.check_database`, который принимает ровно V11: новый head не должен молча обходить version/durability checks;
- определить изоляцию прежних exact-version schema tests, сохранив все assertions, и новую независимую миграционную приёмку; не разрешать общий head pin ради зелёного результата;
- расширить allowed paths только конкретными необходимыми изменениями;65 acceptance F3 остаются обязательны,4 конфликтующих cases не ослаблять;
- после design/проверки вернуться на **Sol6.1 High**, закончить SQL bridge и прогнать весь F3 без исключений.

Не выбирать обходы: future finished_at, переписывание original SQL deadline, failed/interrupted вместо обязательного local timed_out, ожидание SQL wall timeout с объявлением early durable ACK, удаление constraint без нового invariance contract. Никакой миграции main V8 или production startup.

Остаток самостоятельной работы **26–41**: F3 ещё не вычтен, этот preflight не создаёт новый implementation ID. Готовые F1/F2/C1B и внешние gates сохраняются. Это конкретное основание для согласованной смены режима после проверенного checkpoint, а не ожидание «давай дальше».
