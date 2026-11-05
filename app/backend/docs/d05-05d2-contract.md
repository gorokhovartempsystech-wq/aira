# D05-05D2 — backup и bounded upgrade V12→V13

4 ноября 2026, после D1/6edb544, F02/F12. One owned upgrade, retained backup и
crash reconciliation, без удаления/пересоздания рабочей БД. Предыдущая V12 здесь
синтетический совместимый predecessor для приёмки; существование выпущенной V12
не утверждается. Main V8/dev UUID не усыновлять, не мигрировать.

Allowed: новые `src/ara/desktop/postgres_upgrade/`, `src/ara/desktop/_migration_gate.py`,
`tests/acceptance/test_desktop_postgres_upgrade*.py`, этот contract/result/guide/queue.
Единственное изменение старого source — `postgres_schema/_runtime.py`: перенести
процессный claim/release в новый общий gate с прежней D1 семантикой. Gate общий для
D1/D2, поскольку Alembic context process-global, в том числе для разных Home.
Старые tests/migrations/dependencies/остальные source/runner/tasks/progress unchanged.
Все native действия только в новых temporary PG/Home с синтетическим DOCX.

## Lifecycle и API

`UpgradeTools(dump:Path,restore:Path)` frozen pure metadata: absolute/no dot-dot/
control, leaf pg_dump/pg_restore, один bin directory; при construction job совпадает
с bin directory caller-trusted Cluster PgTools. Не capability/проверка подписи.
`UpgradeLimits(max_backup_bytes=8GiB,max_backups=16,timeout_seconds=600)` frozen:
exact positive int, max bytes1024..8GiB, backups1..16, seconds1..600, bool запрещён.
Это технические limits операции, не размер пользовательского DOCX/продуктовый тариф.

`UpgradePreparation(home,cluster,*,migrations:Path,tools:UpgradeTools,limits=None)`
inert и borrowed Home/Cluster. start/view/shutdown(timeout finite0..5)/result/backup_path.
Constructor проверяет types/PID/metadata binding, не читает filesystem/env/SQL/native.
Frozen UpgradeView: phase,error_code,resources_pending. Phases new,preparing,
backing_up,migrating,publishing,ready,not_needed,stopping,closed,failed. Repeat start
idempotent; new shutdown без IO, после него start invalid. PID before mutex,
no copy/pickle, repr/errors без paths/SQL/документов/диагностик бинарников.

UpgradeResult frozen installation_id,system_identifier,database_oid,source_revision,
target_revision,backup_id,backup_sha256,backup_size_bytes. Для not_needed backup fields
None; revision fields current13 либо None для empty. Result — metadata, не schema
readiness; **D1 обязателен после D2**, в том числе после not_needed. backup_path() только
после ready/known cleanup возвращает собственный проверенный data.dump. Path не
принимается как arbitrary restore input; production restore endpoint не входит.

UpgradeError fixed codes validation_error,invalid_handle,upgrade_busy,
upgrade_unavailable,upgrade_recovery_required,unsupported_revision,
backup_limit_exceeded,startup_timeout,cleanup_unknown; unknown→upgrade_unavailable.
Ready/not_needed только после known SQL/command/files/owner/thread cleanup и повторной
deadline/Stop/live-cluster проверки. Не kill при timeout, не retry numeric close.
Unknown native/thread/SQL cleanup удерживает strong shared claim до выхода процесса.
Home и PG не закрываются этим этапом; caller держит их до known completion.

Запускать перед HTTP/analysis/pools либо после их подтверждённого drain. Приложение
не принимает редактирование во время pending upgrade. Это precondition trusted
composition, не обещание исключить будущие внешние SQL writes снимком pg_stat_activity.
Manual modification/source superuser attacks вне supported recovery. Не создавать
пользовательскую историю, cloud transfer или автоматический rollback из архива.

## Допуск и SQL

Known libpq environment overrides reject по наличию до SQL/file mutation, не читать
значения/секреты. Explicit Cluster.connection('aira'), no load_settings/env URL.
PG18/systemID/OID/aira_local/synchronous_commit проверить фактическим SQL.

Без upgrade marker: empty application schema либо current13 → not_needed, никаких
backup/DDL/seed. Этот исход не подтверждает D1 metadata/schema; D1 проверит/завершит
своё первое создание. Неизвестная непустая схема→recovery; V8/other revision→unsupported.
Если marker существует, всегда reconcile, в том числе при SQL13.

Только V12=`0012_docx_continuous_timeout` может обновиться до
V13=`0013_docx_review_preferences`. Требуется exact completed ready.json старой V12,
с Home-derived user/project и теми же PG systemID/OID; no initializing/foreign proof.
Та же record schema aira-schema-ready/1 с revision12. Проверить old structural shape
(Base без docx_review_preferences/docx_review_dismissals/docx_review_receipts), scope
identities, clean analysis fence и отсутствие queued/running analysis. Не reset Fence.
Не выдавать отсутствие old proof за разрешение мигрировать developer DB.

One repeatable-read transaction + try advisory xact lock (1095911745,170302).
Экспортировать bounded snapshot ID через pg_export_snapshot; pg_dump использует именно
его. Transaction удерживается через backup и миграцию. Все old/current data сохраняются,
V13 только добавляет три review tables. Alembic injected Connection/fixed head V13;
no create_all/downgrade. Connect2s/statement60s/lock1s; whole job continuous budget до600s.
Stop до COMMIT rollback своей transaction после возврата in-flight SQL; после COMMIT
не угадывать rollback, оставить protocol для следующего reconcile.

## Backup

Private `Home/backups/postgres` имеет СВОЙ RuntimeOwner/slot, отдельный от PG и schema
owner. Running PG уже удерживает свой process slot; его owner не использовать для
pg_dump. Root содержит только locks и до max_backups canonical UUIDv4 directories700.
Старые bundles не удалять/перезаписывать. Unknown outer entries/unsafe links/modes
fail closed; contents непоинтованных старых bundles не усыновлять. Limit reached
останавливает upgrade, сохраняя предыдущие копии/данные.

Новый UUID directory EXCL; bounded private intent.json и schema-before.json (exact
старые ready bytes<=4096), собственный EXCL600 regular single-link data.dump.pending
с retained FD. pg_dump пишет только этот заранее созданный собственный file; проверить
тот же inode/mode/owner/nlink после known command completion. No chmod чужих files.

Native tools18.*, --version bounded/checked. pg_dump custom full database archive,
--no-password, --lock-wait-timeout=2s, --snapshot=<owned token>, own --file.
Explicit --dbname closed conninfo включает exact socket/user/port/aira, connect_timeout2,
passfile=/dev/null, sslmode/gssencmode disabled. --no-password само не запрещает чтение
.pgpass, поэтому passfile обязателен. Нет shell/partial-table filters/external network.
--no-owner archive option не заменяет --no-owner при restore; native acceptance restore
также explicit no-owner/no-privileges, без --create и без удаления рабочей БД.

Known exit0, streaming SHA256<=1MiB chunks, exact size/inode/mtime checks,
pg_restore --list exit0 на той же копии, bounded capture<=64KiB; stdout/TOC не логировать.
B discards stderr, включая fixed /dev/null warning: не утверждать проверку всех
диагностик. fsync/F_FULLFSYNC, no-replace publication data.dump и backup.json.
Проверены tool success/TOC/hash; runtime не утверждает полное восстановление каждой
копии. Настоящий restore+exact DOCX обязателен в native acceptance на другом temp PG.

Size monitor/hash limit не OS disk quota: возможен overshoot до graceful Stop trusted
pg_dump. Oversize/disk failure → никакой schema mutation, partial сохраняется, success
не обрезается. До начала backup проверить разумный запас free space относительно
pg_database_size, но не обещать защиту от одновременного заполнения диска вне приложения.

backup.json exact fields: schema_version=aira-pg-backup/1,backup_id,installation_id,
user_id,project_id,system_identifier,database_oid,source_revision,source_ready_sha256,
archive_sha256,archive_size,postgres_major18. Canonical UUID/digest/int/binding checked.
Intent содержит те же binding fields без archive hash/size/postgres_major и с version
aira-pg-backup-intent/1. All metadata<=4096. Snapshot ID не persist и не secret.
Final copy immutable; old exact ready находится в schema-before.json.

## Durable upgrade protocol

Schema directory owner/pin удерживается на весь cycle; closed D1 layout расширяется
только для этого updater: upgrade.json/.upgrade.json.pending и ready temp. D1 до
завершения reconcile может reject extra marker — ожидаемое поведение.
Upgrade intent private durable no-replace, exact schema_version=aira-schema-upgrade/1,
installation_id,user_id,project_id,system_identifier,database_oid,source_revision12,
target_revision13,backup_id,backup_sha256,backup_size,source_ready_sha256,
target_ready_sha256. Target ready canonical bytes вычисляются из known bindings13.

1. Backup полностью опубликован/перечитан, включая source ready copy/hash.
2. Durable upgrade intent. Только после него отправлять DDL; before/after marker
   OS faults сохраняют source DB/backup. Orphan backup без intent не переиспользуется
   для нового снимка по одним IDs/revision: сохранить и создать свежий bundle.
3. SQL V12→V13 в той же transaction; shape/identity verification; COMMIT.
4. При SQL13 stage exact new ready13 в .ready.json.pending. Атомарный Darwin
   RENAME_SWAP=2 меняет ready12/new13 местами, сохраняя old12 в temp. Проверить bytes/
   inode до/после, fsync directory/F_FULLFSYNC. Это explicit upgrade replacement,
   не разрешение D1 чинить corrupted published record. Backup хранит exact old bytes.
5. Удалить только распознанный old temp после durable swap, затем intent и barrier.
   Ready13 дальше читается D1 без новых files/расширения D1 parser.

Resume сначала заново проверяет pinned backup/hash/source proof. SQL12+ready12 →
повторить ту же supported migration без нового backup. SQL13+ready12/new temp →
закончить publication; SQL13+ready13/old temp → cleanup. Unknown/missing/conflicting
metadata, corrupt backup, SQL12+ready13, wrong ID/unsupported schema → recovery,
никакой автоматической подмены/restore/drop/recreate. Source12 после intent не
принимает обычные writes приложением; внешнее ручное изменение не поддерживается.
Partial unknown upgrade/ready temp сохраняется; не угадывать успешный обмен по PID.

## Приёмка

Freeze/red; native source V12 с Home IDs и synthetic DOCX, backup/schema13/reopen,
exact old payload in second-cluster restore; snapshot excludes committed change
после export. No-op empty/current13, rejected V8/no-proof/foreign/malformed/active
fence unchanged. Oversize/output/SQL/cleanup errors preserve DB/copies. Crash cuts
backup/intent, before/after COMMIT, after swap/before cleanup; reconcile same IDs,
no duplicate DDL/data loss. Shared gate blocks D1/D2 across different Homes; Stop,
PID/copy, unknown startup/close quarantine. Native Windows release gate отдельно.

Preflight уже пройден: PG18 custom79,411bytes/TOC11,035bytes, real transactional
restore сохранил exact StoredDocx, foreign Home adoption rejected; повтор с exported
snapshot сохранил состояние до поздней правки. Native RENAME_SWAP сохранил оба
inode/bytes, directory fsync/F_FULLFSYNC прошли. Только synthetic temp resources,
known cleanup и удаление своих temporary files; .runtime/d05-05d2-*-preflight.log.

Новые preparation-test fixes допустимы с записью причины без ослабления assertions.
Full/hash/mainV8 snapshot/result/local commit; previous667 hashes unchanged, кроме
единственного явно разрешённого D1 _runtime shared-gate refactor. После — следующий
самостоятельный цикл. Sources: [pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html),
[pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html),
[SQL dump](https://www.postgresql.org/docs/18/backup-dump.html),
[Apple rename flags](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/sys/stdio.h).
