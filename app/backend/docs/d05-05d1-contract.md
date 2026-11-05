# D05-05D1 — схема документов и identity новой локальной БД

4 ноября 2026, после D05-05C/3d5241d, F02/F11/F12. Результат: новый owned cluster
получает текущую схему документов и постоянную локальную область этой установки;
повтор проверяет её и сохраняет данные. Backup/upgrade старых схем — отдельный D2.
Windows native bootstrap, pools/DocumentRuntime lifetime и desktop launcher отдельно.

Разрешены только новые `src/ara/desktop/postgres_schema/`,
`tests/acceptance/test_desktop_postgres_schema*.py`, этот contract/result/guide/queue.
Старые source/tests, migrations/dependencies/runner/tasks/progress не менять.
Никакого создания настоящего Home или миграции main V8. Native acceptance только
temporary Home/PG18.6 с синтетическими документами.

## Интерфейс

`SchemaPreparation(home:DataHome,cluster:ClusterRuntime,*,migrations:Path)` inert:
проверка metadata/PID/type/binding, без IO/native/env/SQL/threads при construction.
Migrations — absolute caller-trusted installation directory без dot-dot/control;
не произвольный пользовательский SQL/code endpoint. Этот DTO не проверяет подпись.
Во время выполнения Home и cluster должны оставаться open/ready; оба borrowed.

`start()->SchemaView`, повтор после start idempotent; new shutdown закрывает без IO.
Frozen view phase,error_code,resources_pending; phases new,preparing,ready,stopping,
closed,failed. `shutdown(timeout=5)->bool`, finite exact int/float0..5, no bool.
Возвращает True только после известного закрытия собственных connection/engine/
journal owner/pins/worker. Stop не закрывает cluster/Home и не обрывает чужие SQL.
Join вне mutex; PID before mutex; no copy/pickle; fixed repr/error без paths/SQL/data.

`receipt()->SchemaReceipt` только успешный ready с known cleanup и live bound cluster.
Frozen fields installation_id,user_id,project_id,system_identifier,database_oid,
revision="0013_docx_review_preferences". Это metadata completed preparation, не
security capability и не разрешение на HTTP/analysis. После ready owned ресурсов
не остаётся; shutdown возвращает True, receipt сохраняется пока cluster ready.

SchemaError fixed codes validation_error,invalid_handle,schema_busy,schema_unavailable,
schema_recovery_required,schema_upgrade_required,startup_timeout,cleanup_unknown.
Unknown code→schema_unavailable. Strong registry удерживает неизвестные outcomes.
Не повторять close по числовому FD после ошибки. Начало Thread.start, которое могло
реально запустить worker перед exception, не позволяет освободить claim преждевременно.

Alembic context proxy process-global: в приложении допускается одна активная
SchemaPreparation, даже для разных temporary clusters. Global claim освобождается
после known cleanup и settled startup. Никаких global CWD/env/logging changes.

## Durable provenance

Отдельный private directory `home.path('backups') / 'schema'` хранит только служебную
proof, без текста документов. Не менять закрытый layout C/Home и не трогать siblings
в backups. Existing ancestors/no-follow/private owner проверяются, root700. Layout
ровно runtime.owner,analysis.slot,initializing.json,ready.json и
.initializing.json.pending,.ready.json.pending. Metadata regular600/singlelink<=4096,
strict UTF8/duplicate/unknown keys/types rejected. RuntimeOwner + free SlotLease probe
до mutations marker; связать root pin с slot inode. Unknown acquisition/close retained.

Оба record содержат ровно schema_version,installation_id,user_id,project_id,
system_identifier,database_oid,revision. schema_version соответственно
aira-schema-intent/1 либо aira-schema-ready/1. UUID canonical и точно Home-derived;
PG system ID/OID точно bound ClusterIdentity, revision точно текущая V13.
Не использовать старые development fixed UUID. Corrupt/foreign proof не исправлять.

Own EXCL temp→full write/fsync/F_FULLFSYNC→Darwin no-replace rename→directory fsync
и storage barrier. Existing published records не переписывать. Ready+его temp
одновременно — ambiguous recovery_required. Correct temp продолжается с теми же
bytes после проверки соответствующего SQL state. Partial initial temp допустимо
убрать только при полностью пустой SQL schema и pristine journal с locks/temp.
Другие повреждённые temps сохраняются. Matching intent после ready можно удалить
только после успешной проверки той же схемы/identity. Published ready никогда не
удалять при ошибке/Stop; lost schema при нём не трактовать как новый первый запуск.

## SQL transaction и повтор

Только explicit worker создаёт NullPool SQLAlchemy Engine с bounded psycopg creator
из текущего Cluster.connection('aira'). Не load_settings/secrets/env URL. Known libpq
environment overrides отвергать по наличию, без чтения значений, до SQL/marker writes.
connect2s/statement60s/lock1s, closed session options/search_path public,pg_catalog.
Whole startup120s continuous including sleep. OS/SQL stall остаётся pending; deadline
не доказывает закрытие. Ресурсы SQL закрываются перед journal pins/owner.

Проверить server PG18, system_identifier, actual current database OID/name/user и
synchronous_commit. One transaction + try advisory xact lock (1095911745,170302).
Busy→schema_busy. No data rows/DDL outside this owned transaction. Alembic получает
явный Connection через config.attributes, fixed target V13; не floating head и не
base.metadata.create_all. Единственный migration head должен быть текущим V13.

1. Без proof разрешить first run только при пустой application schema: стандартные
   public/catalog/information_schema/plpgsql; нет пользовательских tables/views/
   sequences/functions/custom types/schemas. Сначала durable initializing intent.
2. Intent+empty: все существующие migrations до V13, Home user/project (name AIRA)
   и чистый singleton analysis fence revision2/installation UUID — в одной SQL
   transaction. Никакого автоматического усыновления существующих documents.
3. После COMMIT подтвердить SQL state и durable ready marker; удалить matching intent.
   Ready можно выдать только после known cleanup всех собственных SQL/filesystem IO.
4. Intent+already V13 после ACK-loss: проверить exact initial user/project/Fence
   revision2 и отсутствие document/analysis rows, закончить receipt с теми же IDs.
   Ни schema, ни database не удаляются/пересоздаются. Partial committed schema не
   достраивается предположениями.
5. Existing ready: V13/shape, ровно Home user/project с owner, matching installation
   в analysis fence. User documents/drafts/results и fence revision/owner_epoch/
   armed/drained не сбрасывать. Физическое analysis recovery принадлежит supervisor.
6. Старый/будущий известный revision→schema_upgrade_required, без upgrade/downgrade.
   Missing/malformed current schema или чужие bindings→schema_recovery_required.
   Текущая непустая schema без proof тоже recovery_required.

Schema structural gate: exact application table inventory + alembic_version;
имена/PG-типы/nullability columns, PK и FK targets совпадают с текущими models;
неподдержанные views/sequences/user namespaces/functions/types/triggers/rules
отклоняются. Не обещать обнаружение любого ручного изменения SQL expressions/ACL
владельцем компьютера. Тесты проходят реальными существующими migrations; models
не меняются ради совпадения. Preflight на временной PG:22 tables, columns/types/
nullability/PK/FK differences0; ни main, ни source не менялись.

Stop между фазами. Если COMMIT ещё не отправлен, собственная transaction откатывается
после возврата уже принятого SQL. Если COMMIT отправлен, дождаться/согласовать durable
intent при следующем запуске; не выдавать failed ACK за гарантированный rollback.
Нет выдачи Engine/DocumentRuntime из этого этапа; отдельный composition его создаёт
после schema gate и прекращает API до закрытия PG.

## Приёмка

Freeze/red; first schema/seed и repeat с теми же UUID/receipt; реальный синтетический
DOCX roundtrip через existing storage; rejected old V8/foreign/malformed/no-proof
без mutation; wiped schema после ready без пустой замены. Interrupted first tx,
COMMIT ACK-loss и durable marker cuts: reopen сохраняет identity и данные.
Stop/timeout, process claim, PID/copy, unknown SQL/thread close quarantine. Existing
analysis fence не сбрасывается. Все independent old checks unchanged.

Новые test preparation fixes можно исправлять с записью причины, без ослабления
assertions. Targeted/full, final hashes + previous657 unchanged, readonly mainV8
snapshot, result и локальный commit. Затем следующий цикл по очереди.
