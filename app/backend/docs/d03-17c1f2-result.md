# D03-17C1F2 — результат SQL supervisor

3 ноября 2026, Sol6.1 High, после F1 `72fb8f8`. **F2 реализован и проверен** по [контракту](d03-17c1f2-contract.md): V11 singleton ledger, scoped exact claim/heartbeat/recovery и три отдельных bounded SQL engines. Продуктовый startup ещё не подключён; основная БД остаётся V8.

Ledger хранится независимо от document/run/result: terminal SQL, cancel, удаление истории и новый owner UUID не снимают armed. CAS/replay и ordered reads переживают потерю COMMIT ACK, сохраняя исходные attempt/time. Heartbeat возвращает authoritative heartbeat_at той же транзакции; чтение не продлевает lease. Startup snapshot ограничен16 IDs и не включает новые queued entries. Три ленивых pool имеют capacity1/без overflow, отдельные session timeouts/durability settings; импорт не читает настройки/секреты и не открывает подключения.

SQL services фиксируют уже полученные доверенным S/installer proofs. Они **не доказывают** физическое завершение ОС по UUID; armed quarantine после crash остаётся обязательным. Нет bool force-reset или product endpoint. Native cleanup/boot proof, production provisioning, реальная модель и UI не приняты этим циклом.

## Приёмка и согласованные поправки

Freeze **86871c2**, перед source red22failed/1passed по отсутствию V11/API. Узкий parent V10 pin:5 apply calls и isolated world fixture,29 assertions preserved. После source первый общий gate3614passed+24subtests/2failed/41skipped,exit1: SQL comment split в новом oracle и ещё один direct V10 oracle на latest engine.

Никита явно разрешил оба изменения подготовки в чате3 ноября. Применён заранее подготовленный `.runtime/d03-17c1f2-pending-test-preparation.patch`: убрать строки SQL comment перед split; дать только direct V10 oracle отдельный V10 engine. Все **52 assertions новой acceptance и29 старой** совпадают по AST с freeze. DDL/criteria/source не менялись ради этих исправлений. Общие latest-head fixtures по-прежнему проверяют V11, новая acceptance отдельно доказывает сохранность dirty V10 history.

Итоговый targeted: **204passed,32,83s**, включая новую acceptance,27own edges, старую migration acceptance и generic migrations. Проверены actual COMMIT ACK-loss claim/arm/clear, same-ID replay без нового anchor, CAS competition, invalid revisions, foreign worker/source metadata, сохранность success/result, drained handoff, independent fence при удалении run, corrupted/duplicate singleton, bounded snapshot/overflow, endpoint/pool guards. Synthetic данные и только disposable ara_check_<uuid>; не native evidence. Для isolated own tests используется PYTHONPATH=tests/acceptance с общими synthetic fixtures.

Итоговый `bash scripts/check.sh`: **3616passed+24subtests,41skipped,76warnings,402,69s,exit0**. Ruff/format452files прошли. Лог `.runtime/d03-17c1f2-final-full-check.log`.41native skips остаются открытыми gates.

## Сохранность и следующий цикл

Baseline475 финального F1:473 прежних files unchanged; разрешённые исключения — additive models.py и узкий V10 pin. Старый models.py byte prefix сохранён; новые52/старые29 assertions неизменны. Все **483 final gate hashes** совпали до/после. Финальный read-only snapshot совпал со стартом: main V8 `0008_docx_edit_drafts`, schema/counts unchanged, ara_test empty, временных БД0. PostgreSQL оставлен работающим. Первый параллельный preflight snapshot застал собственную временную test DB; повторный sequential snapshot совпал, никаких записей в main не было.

Чужие README/spec/backlog/research/defense файлы, .artifact-build/output сохранены. Архив/секреты не читались, source пользовательских документов не копировался. F1/B3/C1A–E/runner/tasks/progress/dependencies без изменений; нет push/публикации.

При F3 preparation выявлен недостающий exact contract local continuous deadline→SQL terminal и координации с committing/unknown permit. [Preflight](d03-17c1f3-preflight.md) фиксирует конкретные пути/риски. **Далее Astra6 High focused design**, затем Sol6.1 High implementation F3 с exact composition API/allowed paths/acceptance/freeze до source. Explicit start/shutdown, bounded jobs/admission, clock/lease/Stop, native adapters и crash matrix по C1F; production startup и веса не подключать автоматически. При новом архитектурном противоречии завершённый F2 остаётся зелёной границей для Astra pass.

Самостоятельный остаток **26–41 цикл**: F2 вычтен один раз, в текущем блоке остаётся F3. Это оценка нашей части, не готовность релиза без frontend/weights/native gates.
