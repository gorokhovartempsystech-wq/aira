# D05-05C — постоянный локальный cluster и первый запуск на macOS

4 ноября 2026, после D05-05B/f451902, F02/F11/F12. Один пользовательский результат:
приложение само создаёт и повторно открывает свою PG18 БД, не заменяя потерянные
или повреждённые данные пустыми. Поддержка Windows, миграции document schema/backup
перед обновлением и общий desktop launcher остаются отдельными этапами.

Разрешены новые `src/ara/desktop/postgres_cluster/`, `tests/acceptance/test_desktop_postgres_cluster*.py`,
этот contract/result/guide/queue; два файла профиля `_models.py`,`_plan.py` для
описанного ниже optional socket_id. Остальные source/tests/dependencies/migrations/
runner/tasks/progress не менять. Main V8 не открывать для реализации, не мигрировать.
Все native tests — синтетические временные Home/cluster, без настоящего профиля.

## Дополнение к D05-05A: свежий endpoint

`make_plan(...,socket_id:UUID|None=None)` — optional explicit UUIDv4 только для Mac.
По умолчанию прежнее поведение/приёмка неизменны. Если передан, он определяет только
socket_root=/private/tmp/aira-pg-<socket_id.hex>; installation_id остаётся прежним.
Plan хранит private repr-hidden `_socket_id`, validate_plan учитывает его. Windows
socket_id отвергается. Старый контракт не переписывать, новые tests добавляются.

Runtime выдаёт свежий socket_id на каждый запуск и создаёт этот private700 directory
EXCL; существующий каталог не усыновляет. Это отделяет readiness от оставшегося
вручную запущенного сервера той же БД. После подтверждённого завершения своего PG
можно удалить только свой пустой socket directory с проверкой identity; никаких
recursive unlink/socket PID-file cleanup. Не удалять неизвестное содержимое.

## Интерфейс и последовательность

`PgTools(target,postgres:Path,initdb:Path,control:Path)` frozen pure metadata:
target macos-arm64/macos-x86_64; три absolute Path из одного bin directory, leaf
postgres/initdb/pg_controldata, no dot-dot/NUL/control. Это caller-trusted binaries
из проверенного immutable installation; metadata не доказывает подпись файлов.
`ClusterRuntime(home:DataHome,tools:PgTools)` inert: metadata/type/PID validation
без filesystem/SQL/process/secret/native lookup. Home borrowed и не закрывается.

`start()->ClusterView` однократно начинает background worker, повтор idempotent.
view frozen phase,error_code,resources_pending; phases new,preparing,starting,ready,
stopping,closed,failed. new shutdown не создаёт cluster; subsequent start invalid.
`shutdown(timeout0..5=5)->bool` только graceful Stop/finite join, True после известного
закрытия своих SQL/commands/owner/pins/thread. Нет force kill при timeout. Unknown
native/thread outcome удерживается strong registry; повтор не обходит pending.
PID before mutex, no copy/pickle. Ошибки fixed ClusterError: validation_error,
invalid_handle,platform_unavailable,cluster_busy,cluster_unavailable,
cluster_recovery_required,startup_timeout,cleanup_unknown; unknown→cluster_unavailable.

`connection(database='aira')` отдаёт detached immutable libpq metadata только ready,
для aira/postgres, при ещё running owned command и открытом Home. `identity()` —
frozen ClusterIdentity(installation_id,system_identifier,database_oid,postgres_major)
только ready. SQL readiness не означает мигрированную document schema: product API
подключается только после следующего schema gate. Repr/errors/view скрывают paths,
stdout/SQL/идентификаторы OS. Ключи лицензии/пароли не читаются и не записываются.

На start проверить native target/OS account и окружение до cluster mutations:
не использовать ambient libpq PG* overrides. Проверять присутствие известного
закрытого списка PG environment keys без чтения/печати их значений; при наличии
вернуть cluster_unavailable. Не менять global os.environ. В production весь Python
будет запущен launcher с узким env. Peer/private socket, passfile=/dev/null,
sslmode/gssencmode disabled; никакого load_settings()/secrets.env в bootstrap.

Общий startup budget120s sleep-counting; SQL connect2s/statement2s/lock500ms.
Timeout просит graceful Stop, а не объявляет ресурсы закрытыми. Если OS/SQL ещё не
вернулись, worker/resources остаются pending. Перед каждой следующей фазой учитывать
Stop; уже отправленную DDL/COMMIT дождаться и согласовать по той же БД при restart.

## Файлы и происхождение данных

Root — home.path('postgres'), private700/current euid, nofollow pinned dir handles,
проверенные ancestors. Сначала known-layout inspection, затем RuntimeOwner; успешный
SlotLease probe обязателен до ЛЮБЫХ изменений cluster files. Связать собственный
root FD с owner через identity analysis.slot/SlotLease и recheck pathname. Закрывать
только свои descriptors; ошибка close означает quarantine, не повтор по тому же FD.

Закрытый layout: runtime.owner,analysis.slot; initialization.json,prepared.json;
data18,.data18.pending; server.conf,pg_hba.conf,pg_ident.conf; cluster.json;
их собственные `.<basename>.pending` files для atomic metadata publication;
до3 retained private directories failed-init-<canonical UUIDv4>. Непредусмотренные
entries/unsafe links/modes/owners — recovery_required без удаления/ремонта.
Root/metadata single-link regular0600; metadata<=4096bytes, strict UTF8 JSON,
duplicate/unknown keys и неподходящие UUID/types отвергаются. Config files exact
generated bytes для этого профиля. Existing published files никогда не переписывать.

initialization.json exact schema_version="aira-pg-initialization/1",installation_id,
target. prepared.json exact schema_version="aira-pg-prepared/1",installation_id,
target,system_identifier. cluster.json exact schema_version="aira-pg-cluster/1",
installation_id,target,postgres_major=18,system_identifier,database_name="aira",
database_oid (exact int1..uint32max). IDs canonical; system_identifier nonzero
decimal uint64 без leading zeros. installation/target всегда совпадают с Home/tools.

Atomic private metadata: exclusive own temp -> full write/fsync -> no-replace rename
через Darwin renameatx_np/RENAME_EXCL -> fsync directory + F_FULLFSYNC подтверждение.
Не fallback на replace. Published marker сохранять при любой ошибке. Восстанавливать
корректный metadata temp с теми же bytes; некорректный private bounded temp можно
убрать только при доказанном первом запуске без final cluster/data. Нельзя применять
это к повреждённому published record или рабочему cluster.

## Новый cluster и restart

Признать pristine только layout с locks/допустимым собственным metadata temp,
без данных/неизвестных files. Последовательность:

1. Durable initialization intent, затем initdb в отсутствующую .data18.pending
   через OwnedCommand; успешный exit0 и известный cleanup/slot-free обязательны.
2. Ограниченно прочитать PG_VERSION и pg_controldata staging, подтвердить PG18,
   system ID, block size8192/checksums1 и shut-down state; записать durable prepared.
   pg_controldata — metadata, не самостоятельное доказательство CRC integrity.
3. No-replace rename .data18.pending→data18, durability barrier. Сгенерировать
   private exact configuration, не подменять существующий несовпадающий файл.
4. Запустить owned foreground PG на свежем socket; дождаться своего live command
   и check_observation на postgres против независимого prepared system ID.
5. Только в этой доказанной initialization ветке создать aira, если её ещё нет.
   При ACK-loss/restart читать существующую aira, проверить owner/UTF8/C/C, сохранить
   её OID. Не удалять/пересоздавать/очищать уже существующую БД.
6. Durable publish cluster.json с system ID/OID. Проверить aira SQL profile, убрать
   только matching initialization/prepared markers, fsync до выдачи ready.

Для existing cluster.json никогда initdb/CREATE DATABASE при отсутствии aira.
Проверить data18/PG_VERSION/metadata, запустить свой PG и потребовать прежний system
ID и прежний OID/owner/locale aira. Missing/changed DB → recovery_required, без пустой
подмены. Matching leftover init/prepared markers после crash cleanup можно убрать
после проверки этой же БД; несовпадающие/повреждённые не угадывать.

Crash после prepared/staging или data rename до final record: valid matching
intent+prepared разрешают закончить публикацию/SQL шаги с тем же system ID.
data18 без final record И без полноценного prepared proof — recovery_required.
Final record без data18, data18+staging вместе, record/temp conflict — recovery_required.

Если есть только valid initial intent и incomplete .data18.pending без prepared
и без data18/final, это никогда не выдававшиеся приложению данные. После slot-free
admission сохранить stage целиком no-replace rename в failed-init-UUID, fsync;
запустить новый initdb только на теперь отсутствующий stage. Не удалять backup.
До3 таких сохранённых failures; дальше recovery_required, без бесконечного роста.
Unsafe/missing provenance не позволяет такой повтор. После ready init proof удалён,
поэтому потеря final record в рабочем cluster не выдаётся за первый запуск.

Закрытие приложения останавливает только свой OwnedCommand; existing/stale PG PID
files не читать для kill/adoption и не удалять. Guardian/slot protocol обеспечивает
занятость managed descendants; manual modification/запуск БД внешними средствами
не превращается в поддерживаемый recovery path. Source data/config/records
сохраняются при failures. Runtime root owner освобождать только после known PG stop.

## Приёмка

Freeze/red; first ready/reopen stable IDs/OID/committed synthetic rows; новая socket
identity каждый launch; shutdown с открытой транзакцией остаётся pending до COMMIT/
close. Wrong/missing/duplicate record, wrong OID/absent aira, unexpected files/links/
modes — no replacement. Runtime owner/slot contention, PID/copy/strong retention,
startup/SQL/cleanup faults. Native crash cutpoints intent, initdb/stage, prepared,
data rename, DDL ACK-loss, final record/marker cleanup; restart same identity там,
где опубликована proof, и сохранённый partial stage в доказанной first-only ветке.
Native PG18.6 только temporary roots, no production profile. Windows pending.

Для новых tests preparation fixes допустимы с записью причины без ослабления
assertions. Старые tests unchanged. Full/hash/mainV8snapshot/result/local commit.
Hash exception только два явно разрешённых profile files; объяснить additive API.
