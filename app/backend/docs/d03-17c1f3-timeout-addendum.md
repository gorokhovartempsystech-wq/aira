# D03-17C1F3 — сохранение continuous timeout

3 ноября 2026. Уточнение [контракта F3](d03-17c1f3-contract.md) после
[воспроизведённого конфликта](d03-17c1f3-schema-preflight.md). Никита поручил
продолжать проектирование и реализацию до результата на Astra с очень высоким
усилием, без остановки для смены модели. Это завершение того же F3, не новый ID.
Продуктовые границы F06–F08/F12 не меняются.

## Решение и инварианты

V12 `0012_docx_continuous_timeout` добавляет в `docx_analysis_runs` поле
`timeout_basis TEXT NOT NULL DEFAULT 'wall'`. Прежние строки и старые writers
получают `wall`. Значение имеет смысл только для timed_out; `continuous`
допускается исключительно у timed_out. Новое CHECK:

```sql
timeout_basis = 'wall' OR (timeout_basis = 'continuous' AND status = 'timed_out')
```

В `ck_dar_terminal_reason` меняется только условие timed_out:
`error_code='deadline_exceeded' AND
(finished_at >= deadline_at OR timeout_basis='continuous')`.
Все прежние CHECK/FK/unique/index guards, ограничения времени и terminal shape
остаются. `finished_at=max(SQL now,created_at)`, исходный deadline неизменен.
`wall` по-прежнему запрещает ранний timed_out. SQL CHECK проверяет целостность,
а не подлинность clock evidence: доверие к local decision обеспечивает прежний
sealed ExitAuthority и проверки exact scope/claim/owner в F3.

Только F3 `_terminal.apply_exit` выставляет `continuous`, когда sealed reason
равен deadline, scope сохранён и SQL now ещё раньше исходного deadline. Если
SQL deadline уже истёк, сохраняется wall. Existing terminal остаётся неизменным,
в том числе basis, время, результат и fence. Приоритет scope/SQL/first reason
из §6.2 сохраняется. Публичные DTO/status/error codes/wire не расширяются.

Upgrade выполняет transactional ALTER с проверкой constraints; никаких
перезаписей bytes, timestamps, source/result, attempts или launch ledger.
Downgrade берёт ACCESS EXCLUSIVE на runs и отказывает при **любой** continuous
строке, даже если её finished_at уже не раньше deadline: потеря basis тоже
потеря истории. После ожидания writer проверка повторяется под тем же lock.
При отказе вся migration откатывается, включая alembic revision. Для истории
только wall восстанавливается точное V11 constraint и удаляется новое поле.
Предыдущий V11 gate на provisioned ledger продолжает действовать при дальнейшем
откате к V10. Не удалять историю ради downgrade.

## Совместимость и точные границы изменения

Текущий binary требует V12. F2 `check_database` по-прежнему принимает **один
точный head**, теперь V12; V11/V10/future отвергаются до admission/launch.
Durability, bounded pools и singleton checks неизменны. Автоматической migration
или provision при startup нет. Main `ara_dev` остаётся V8; всё исполняется только
на disposable synthetic DB. Older binary не принимает V12 — штатный fail-closed
при несовпадении приложения и схемы, не обещание двусторонней runtime совместимости.

Дополнительные разрешённые source paths: новая migration V12; только
DocxAnalysisRun column + два CHECK в `src/ara/models.py`; строка expected version
в `supervisor/database.py`; прежние F3 modules для завершения композиции.
Исторические migrations V1–V11/DDL, B3/C1B, runner/tasks/progress/check/conftest,
зависимости, UI/HTTP/native driver contracts не меняются.

Исторические тесты V11 продолжают проверять V11: в двух migration cases F2
вызовы upgrade явно получают V11; в двух параметризациях проверки broken singleton
создаётся отдельная V11 DB. Это только подготовка: прежние assertions побайтово
сохраняются. Остальные tests, в том числе все 65 F3 cases и generic head/ORM gate,
работают с актуальным head. Не закреплять общий fixture на старой версии.
Это точечное разрешение в подготовленном до реализации addendum, а не ослабление
приёмки из-за неудачного результата. Разрешённые test paths для подготовки:
`tests/acceptance/test_docx_analysis_supervisor_sql.py` (3 explicit revision args),
`tests/docx_documents/test_analysis_supervisor_sql_edges.py` (один fixture setup).

## Дополнительная приёмка

Новый `tests/acceptance/test_docx_analysis_continuous_timeout.py` фиксируется до
source. Независимые checks: сохранение всех прежних статусов/данных/ledger при
upgrade/repeat; head/ORM; точный downgrade для wall; rejection invalid basis,
non-timeout continuous и раннего wall timeout; early/late continuous retention;
writer commit/rollback во время downgrade; exact startup version;
композиционный local timeout с честными timestamps и durable replay.

Сначала red новой приёмки, затем source, целевые F3/schema/regression проверки,
полный `bash scripts/check.sh` без исключений, snapshot main и локальный commit.
Все 65 ранее зафиксированных F3 cases обязательны. Native Windows/real model/
production provisioning/boot recovery остаются отдельными gates. Частичный WIP
`98724fe` не становится завершённым задним числом.
