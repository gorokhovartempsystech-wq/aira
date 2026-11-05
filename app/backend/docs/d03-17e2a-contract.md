# D03-17E2A — схема постоянных фильтров и скрытия

3 ноября 2026. Отдельный цикл F08/F09 после E1. Только additive V13 schema/ORM,
compatibility gate supervisor и сохранность миграций. Реализация CAS/read/write
и подтверждённого hide по B2 результату — следующий E2B; HTTP — E3; перенос по
изменённому source — E4. Main V8 не мигрировать. Не объявлять persistent UI готовым
по одной схеме.

Allowed: новая `migrations/versions/0013_docx_review_preferences.py`; append-only
3 model classes в `src/ara/models.py`; exact allowed versions V12/V13 в
`src/ara/docx_analysis_worker/supervisor/database.py`; новая independent acceptance
`tests/acceptance/test_docx_review_preferences_schema.py`; точечная подготовка
исторического V12 test file (ниже); docs contract/result/queue. Остальные source,
old migrations/tests/dependencies/runner/tasks/progress неизменны.

## Таблицы

1. `docx_review_preferences`: document_id UUID PK/FK docx_documents.id; revision
BIGINT>0; disabled_types JSONB NOT NULL default[] — только8 canonical subsets
sorted из contradiction/duplicate/formulation (никаких duplicates/unknown/nested
values); show_questions BOOL defaulttrue; show_hidden BOOL defaultfalse;
created_at/updated_at timestamptz NOT NULL defaultclock_timestamp(), finite и
updated>=created. Отсутствующая строка в будущей service означает virtual revision0
и default prefs, read не создаёт её.
2. `docx_review_dismissals`: composite PK(document_id,dismissal_key); FK document
→preferences; dismissal_key TEXT `dh-`+64lowerhex; source_run_idUUID,
source_result_sha256TEXT64hex, source_finding_idTEXT`df-`+64hex; compositeFK
(document_id,source_run_id,source_result_sha256)→results(document_id,run_id,
result_sha256); hidden_at_revisionBIGINT>0; created_at timestamptz finite default
clock_timestamp(). Только active hides; explicit unhide удаляет row, receipts
сохраняются. Key вычисляет будущий service по заново проверенному E1 finding,
никогда не принимает arbitrary key от клиента. Сам FK не доказывает validfinding.
3. `docx_review_receipts`: PK(document_id,command_idUUID); FK document→preferences;
UNIQUE(document_id,revision); expected_revisionBIGINT>=0; revisionBIGINT>0 и
revision-1=expected_revision; kindTEXT preferences/hide/unhide; command_dataBYTEA
1..16384 и command_sha25664hex; response_dataBYTEA1..2048 и response_sha25664hex;
created_at finite timestamp defaultclock_timestamp(). Receipt содержит только
small metadata ack, не весь growing hidden set и не DOCX/result text. Хеши проверяет
service, CHECK проверяет shape. Один accepted new command расходует одну revision;
exact replay возвращает original ack без повторного изменения. Overflow отвергать.

Все NOT NULL. Только явные named constraints; обычные FK NO ACTION, без silent
cascade removal истории. No initial rows, no migrations меняющие old histories.
Никаких новых индексов на чужие таблицы; собственных PK/unique достаточно.

## Downgrade / совместимость

V13 downgrade: ACCESS EXCLUSIVE lock prefs→dismissals→receipts, под lock проверить
**все3 пусты**. Любые пользовательские данные запрещают downgrade с safeRuntimeError
`Cannot downgrade DOCX review preferences`. После отказа schema/version/data
полностью прежние. Empty downgrade drops receipts→dismissals→prefs и точно
возвращает V12. Writer commit/rollback race обязательна: проверка после lock.

Supervisor check_database принимает только V12 и V13; старые10/11 и unknownfuture
остаются recovery_required. V13 добавляет только независимые review tables,
исходные F3 SQL invariants и native handling не меняются. Feature E2B будет явно
требовать V13, S может читать прежнюю V12 без preference feature. Auto migration
не появляется; DB/engine config/тайм-ауты не меняются.

## Историческая приёмка V12

Конкретный конфликт найден **до реализации**: old
`test_docx_analysis_continuous_timeout.py` в3 местах вызывает head без версии,
проверяя именноV12; её pg_engine cases тоже ожидают V12 после отказа downgrade.
При V13 head надо по-прежнему запускать эти исторические проверки на V12.
Разрешённая подготовка только этого файла:
-3 `apply_migrations(engine)` → `apply_migrations(engine,V12)`;
-local fixture pg_engine(empty_pg_engine,apply_migrations) создаёт V12;
-future-version negative test поднимает V12 перед подстановкой0099_future.
Все assertions/проверяемые случаи и expected values сохраняются. Это переход
подготовки на явно заданную версию, не ослабление старой приёмки после failure.
Новая independent acceptance проверяет V13 и совместимость12/13 отдельно.
Основание выполнения: автономная команда Никиты3ноября; не приписывать ему
отдельное подтверждение конкретных строк. Exact patch фиксируется до source,
AST asserts сравнить с исходным коммитом. Shared conftest не менять.

## Gate

Freeze/red independent tests. Upgrade repeat/ORM matches/all old rows+schema
unchanged outside3tables; defaults/constraints/FK crossdoc/result hash; nonempty
rollback/blocked downgrade; writer races;12/13 accepted, older/future rejected.
Full scripts/check.sh, baseline hashes except exact allowed files, main V8/counts
unchanged/empty ara_test/no temp DB; result/local commit. Дальше E2B.
