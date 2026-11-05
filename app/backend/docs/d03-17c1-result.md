# D03-17C1 — результат проектирования

1 ноября 2026, Astra 6 High, по прямой команде Никиты. Основание — B3B `7cd3b54`. Завершён **архитектурный цикл**, implementation не выполнялся: [проект](d03-17c1-design.md), [первый контракт C1A](d03-17c1a-contract.md), согласованные ссылки в D03-17 и очереди. Runtime code, frozen tests/DDL/contracts, runner/tasks/progress и основной продуктовый объём не менялись.

## Принятые технические решения

- Разделены физическое прекращение вычисления, локальное право начать commit и подтверждённый SQL результат. Stop до permit запрещает публикацию; Stop после permit/при unknown commit остаётся pending до ordered-lock reconciliation. Нельзя обещать rollback уже отправленного COMMIT, выдавать ранний cancelled ACK или удалять успешную историю. Это явное уточнение прежней слишком широкой формулировки D03-17, не скрытое ослабление B3B tests.
- Guarded completion добавляется отдельно, с повторной B2B проверкой DB source/request и прежними SQL fences. Новые supervisor paths не вызывают старый unguarded complete как обход Stop. Unknown commit не вызывает повторный inference; unlocked SELECT не доказывает rollback.
- Выбраны conservative continuous-clock deadlines, включая сон компьютера, короткий control dispatcher и независимый guardian. Heartbeat не продлевает общий срок. Зависание Python/БД прекращает модель по последнему permit, не создаёт безлимитные DB jobs.
- Private bounded frame protocol, explicit environment/handle allowlist, отсутствие model DB credentials и raw content logs. Ready/result frame не равен подтверждённому успеху: требуется clean exit/EOF и B2B+SQL gates.
- Два lifetime locks: runtime owner и наследуемый model slot. macOS guardian владеет прямым child и сохраняет leader identity до последнего сигнала; Windows использует retained handles/Job Object. Неизвестный PID не разрешает kill. Допущен только threads-only pack; произвольное дерево daemon processes не объявлено безопасно управляемым.
- Шесть implementation циклов: **C1A control, C1B guarded SQL, C1C wire, C1D macOS, C1E Windows, C1F scheduler/recovery**. Для C1A зафиксированы API, состояния/переходы, allowed paths и acceptance matrix. Остальные получат отдельные frozen contracts до кода.

Проверены проектные cut points: Stop до/после permit, потеря ACK до/после commit, rollback/locked absence, stale permits, поздний heartbeat, resume/clock rollback, startup queued IDs, утечка control writer, premature PID reap, повторный spawn до cleanup, guardian failure/slot retention. Это review проекта; subprocess/native/end-to-end поведение **ещё не проверено реализацией**. Первичные технические источники Apple/Microsoft/Python/PostgreSQL/Psycopg указаны рядом с соответствующими решениями. Локально подтверждено: Python3.12.14/Darwin не предоставляет os.waitid; проект macOS использует другую границу ownership.

## Проверка и сохранность

Обязательная **`bash scripts/check.sh` прошла: 2957 tests +24 subtests,76 warnings,343,54 секунды,exit0**. Ruff и format прошли,358files. Лог `.runtime/d03-17c1-full-check.log`. Это регрессионная проверка существующего приложения после documentation-only изменений, не приёмка будущего supervisor. Новых runtime tests в design-cycle не добавлено; freeze/red C1A впереди.

Read-only baseline до/после совпал: `.runtime/d03-17c1-start-runtime.json`, `.runtime/d03-17c1-final-runtime.json`; main ara_dev остаётся V8, schema/counts unchanged, ara_test пуста, временных ara_check БД0. Содержимое пользовательских документов не читалось. Проверены relative links новых документов и `git diff --check`; src/tests/migrations/contracts/ralph/scripts/pyproject не менялись.

Чужие dirty README/старые specs и untracked пользовательские материалы сохранены и не включаются в commit. Архив, secrets, Word и model не использовались. Только локальный commit; GitHub upload/push, миграция рабочей БД и публикация не выполнялись. PostgreSQL оставлен запущенным.

## Передача следующему циклу

**Сейчас вернуться на Sol 6.1 High и реализовать D03-17C1A.** Сначала frozen acceptance/red, затем narrow implementation/full gate/result/local commit; дальше отдельные циклы по очереди без повторного «дальше?», как разрешил Никита. На этой границе остановка только для согласованной смены режима.

Ограничения остаются: C1 пока проект, native Windows не доступна в текущей macOS среде, двойной отказ guardian/backend на macOS может оставить fail-closed busy slot, новый engine partial/pairwise и real weights требуют C2, полный DOCX/native Word/лицензия/desktop/frontend не завершены. Один успешный gate старого приложения не доказывает готовность этих частей.

Самостоятельный остаток **31–46 циклов**, включая шесть C1. Прежняя оценка26–41 считала C1 одной крупной строкой; детализация1→6 добавляет5 циклов, без новых продуктовых функций. Завершённый дизайн повторно не включён. Диапазон — рабочая оценка, не потолок; вклад Ани/Артёма и native release gates не объявляются нашей завершённой работой.
