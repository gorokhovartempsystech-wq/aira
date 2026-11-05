# D03-17B2A — аддитивная схема хранения DOCX analysis

1 ноября 2026. Подготовлено в design-cycle B2, реализация следующей на **Sol 6.1 High**. Основание: [B2 design](d03-17b2-design.md), F06–F10/F12. Перед работой читать current-product-scope.md. Это не выполненный цикл; production source пока отсутствует. Родительский шаг подготовки фиксирует новый контракт и независимую приёмку до implementation.

## Единственный результат цикла

Добавить Alembic revision **`0010_docx_analysis_storage`**, `down_revision='0009_docx_editor_checkpoints'`, и ORM `DocxAnalysisSource`, `DocxAnalysisRun`, `DocxAnalysisAttempt`, `DocxAnalysisResult`. Четыре таблицы точно по [d03-17b2-schema.sql](d03-17b2-schema.sql): это нормативный DDL, не ещё один путь установки схемы. Перевести в обычный Alembic/SQLAlchemy style проекта; runtime не читает SQL из docs.

Все существующие tables/columns/FK/index/defaults, исходники V1–V9, source reader/B1, /health/API и scopes неизменны. Никакого запуска модели, CRUD/start/cancel worker, новой route, UI, secret I/O, scheduler или новой зависимости. Схема лишь готовит хранилище; функция проверки/восстановления результата пользователю ещё не появляется.

## Точная семантика

- `sources` PK(document_id,source_sha256); byte cap32MiB. Старые docx_documents не получают новый unique key, колонку или CASCADE. Source/scoped FK через document, ownership в runtime B3.
- `runs` PK id; unique(document_id,id), key, accepted_order, publication triple и attempt-binding triple; partial active index. Все другие partial indexes/названия/порядок полей как в DDL. Положительные bigint counters без auto-increment; lifetime300s, immutable source/revision/command/profile/execution pin для будущего сервиса.
- `attempts` PK id, unique run_id и scoped triple, request cap8MiB, claim_fence=1. Взаимные deferred FK гарантируют одновременно существующие run pointer и attempt. В этой версии один inference/run; retry всегда новый run.
- `results` PK run_id, scoped digest unique, FK к одной attempt; reply4MiB/result8MiB. Succeeded требует exact result digest через deferred FK, result через reverse FK требует succeeded status. Нельзя commit только одну половину публикации.
- Scalars/NULL shape enforce именно final-state invariants; SQL не доказывает JSON/SHA/immutability/transition authorization. Не добавлять самодельные JSON validators или triggers ради обхода этого разделения.
- Все FK default NO ACTION, без ON UPDATE/DELETE CASCADE; только четыре явно указанных deferred constraints: `fk_daa_run`, `fk_dar_attempt`, `fk_dax_success`, `fk_dar_result`. Остальные immediate. Cyclic constraints именованы и создаются после обеих соответствующих таблиц; ORM use_alter допустим, introspected shape должен совпасть.
- NOT NULL/default/тип/column set точны. `TIMESTAMPTZ`/timezone=True и finite checks, lowerhex64 hashes, ASCII profile/policy bounds, размеры BYTEA, error allowlist — DDL. SQL UNKNOWN не должен пропускать required paired fields. SHA check — regex, не equality bytes; pgcrypto не нужен.

### Downgrade

В одной Alembic transaction получить ACCESS EXCLUSIVE locks **runs → attempts → results → sources**, потом проверить EXISTS любой строки в любой из четырёх таблиц. Если есть хотя бы одна — safe `RuntimeError('Cannot downgrade while DOCX analysis records exist')`, никаких строк/SQL details в ошибке. Версия V10/schema/данные остаются прежними. Остановленный/пустой result не даёт разрешения удалить run/idempotency history; даже orphan source запрещает downgrade.

Если все четыре пусты: явно снять cyclic FK, удалить results/attempts/runs/sources в зависимом порядке. Никаких DROP CASCADE/DELETE/TRUNCATE/auto-cleanup. V9 checkpoint dirty gate по-прежнему работает при дальнейшем downgrade; нельзя обходить его из новой миграции. Runtime во время upgrade/downgrade не работает; lock-before-check обязателен как дополнительная защита от случайной конкурентной записи.

## Разрешённые пути и подготовка совместимости

Implementation:

- `src/ara/models.py`: только необходимые imports и четыре новых класса;
- `migrations/versions/0010_docx_analysis_storage.py`;
- собственные `tests/docx_documents/test_analysis_storage_schema_*.py`.

Parent preparation до freeze:

- новая independent `tests/acceptance/test_docx_analysis_storage_migrations.py`;
- узкий pin старой V9 migration приёмки ниже;
- этот контракт/SQL уточняются только до freeze; после freeze любое расхождение решается как изменение контракта, не правкой assertions ради pass.

Report после реализации: `docs/d03-17b2a-result.md`, ссылки очереди/D03-17/B2. Runner/tasks/progress, AGENTS, scripts/check.sh, общий `tests/acceptance/conftest.py`, dependencies, contracts/ и вся остальная приёмка остаются неизменны. Пользователь уже разрешил последовательные ограниченные циклы; переход B2A→B2B после проверенного результата разрешён. Не требовать смены на Astra для механического продолжения этого дизайна.

**Narrow V9 pin:** в `tests/acceptance/test_docx_checkpoint_migrations.py` четыре вызова `apply_migrations(empty_pg_engine)` в двух V9-specific тестах (три в `test_upgrade_repeat_clean_downgrade_preserves_all_v8_data`, один в `test_downgrade_refuses_unsaved_work_atomically`) заменить на `apply_migrations(empty_pg_engine,V9)`. В `tests/docx_documents/test_checkpoint_schema_edges.py` один такой вызов fixture `parent` также pin V9. Итого **5 вызовов**, ноль изменений assertions/seed/locks/boundaries или их количества. Parametrized tests продолжают исполняться. Точное количество сверить перед freeze; чужие правки не откатывать.

Основание pin: эти тесты специально assert exact V9 и сравнивают все предыдущие tables до/после V8↔V9. Новый head V10 превращает их в случайный тест другой миграции и делает старое условие логически несовместимым. Аналогичное parent-level уточнение уже есть в D03-16B1/V8. Этот новый контракт **явно ограничивает** подготовительную правку; внутренний исполнитель её не расширяет. Общий `apply_migrations` default='head' и generic migration→ORM test остаются на latest head. Новая приёмка обязана отдельно доказать head=V10 и сохранность **всего** V9, включая dirty checkpoint. Сегодня design-cycle тесты не меняет.

## Независимая приёмка до source

Использовать только синтетические документы и отдельные `ara_check_<uuid>` через существующие fixtures. Ни миграций, ни записи в ara_dev/ara_test. Шаги SQL constraints, включая deferred ones, проверять как commit/`SET CONSTRAINTS ALL IMMEDIATE` failures с rollback, а не только successful execute. Каждая case должна проверять нужное нарушение на остальном допустимой строке, не маскироваться отсутствующим parent FK.

1. Empty latest upgrade и repeat → V10; schema signatures одинаковы; Base.metadata соответствует **всему** head. V9→V10→repeat сохраняет schema/rows всех прежних tables: legacy Markdown versions/runs/reviews/drafts, DOCX original/current+receipt/edit draft, checkpoint working/pending/empty. Открытый checkpoint не блокирует upgrade.
2. Exact four column sets/types/nullable/defaults, named PK/UQ/FK, `DEFERRABLE INITIALLY DEFERRED` только перечисленных четырёх, exact index column order/predicates. Сравнить ORM тоже; Alembic может не сравнивать CHECK predicates автоматически — проверить отдельно.
3. Synthetic valid final rows: queued; atomically bound running attempt; cancel_requested; success+result; failed/cancelled/timed_out до и после claim. Правильный success может commit при INSERT result до UPDATE run, если constraints отложены; преждевременный SET IMMEDIATE отвергает незавершённую пару.
4. Success без result, result без success, только attempt без run pointer, pointer без attempt, wrong digest/foreign attempt/document/run — отказ именно deferred FK при commit. Wrong result document не должен ссылаться на одноимённые данные другой области.
5. Duplicate source/key/order/active run/attempt/result отклоняются. После terminal допускается новый активный run того же документа с новым ключом/order; другим документам независимый active run разрешён. Cancel_requested всё ещё занимает active slot. Race двух транзакций на partial unique index: максимум один commit; после rollback проигравшая не имеет source/key receipt.
6. NULL-пары, неизвестные status/stage/kind/error, zero/overflow counters, fence matrices, NaN-like timestamps (`infinity/-infinity`), неверный 300s deadline, expired/слишком длинный lease, nonempty result при failure, no_findings с ненулевым count. Заданные строки проверяются INSERT **и UPDATE**.
7. Bytes exact max/+1 для source/command/snapshot/execution/request/reply/result; optional result digest validation; hash case/length; ASCII profile/policy length. Invalid UTF-8 внутри BYTEA сам SQL **может** сохранить — decoder test B2B должен отвергнуть; не писать ложный DB test, будто это UTF-8 колонка.
8. Clean V10→V9→V10: прежний V9 schema/data сохраняется; все новые tables исчезают/возвращаются пустыми. Dirty downgrade с одной source, с failed/queued run, с bound attempt или complete result отказ/полный rollback. Нет скрытого удаления, нет CASCADE через старый document.
9. Race downgrade с uncommitted writer: если writer commit, миграция ждёт затем отказывает; если rollback — чистый downgrade возможен. Проверять PostgreSQL blocking observation, не случайный sleep. Повтор после отказа не меняет данные/version. Multi-step downgrade с dirty V9 checkpoint сохраняет V10 при transaction rollback.
10. Fresh-process imports моделей/миграции не читают secrets, пользовательские файлы, сеть/БД и не запускают процессы. Зависимости прежние, engine принадлежит caller.

Новый тест должен упасть red до четырёх ORM/migration, старые pin tests остаться зелёными на V9. Freeze parent contract/приёмка/pin отдельным локальным commit; implementation source/own edges следующим. `bash scripts/check.sh` после реализации, реальный exit/count/time и baseline main до/после записать. Вызовы database через обычное sandbox escalation. Стандартную проверку не менять и не сокращать ради новой схемы.

После зелёного B2A: результат/локальный commit, затем готовить B2B codec contract/frozen acceptance на Sol. Не запускать новую миграцию основной БД, не публиковать недопроверенный код в репозиторий Артёма и не считать B3/C1 уже реализованными.
