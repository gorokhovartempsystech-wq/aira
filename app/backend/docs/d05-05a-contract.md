# D05-05A — профиль PostgreSQL18 и проверка готовности

4 ноября 2026. После D05-04/a47aa91; F02/F11/F12. Этот цикл реализует pure
конфигурацию локального PG и проверку наблюдаемого состояния, а не управление
процессом/файлами. Разрешены новые `src/ara/desktop/postgres_profile/`,
`tests/acceptance/test_desktop_postgres_profile*.py`, contract/result/guide/queue.
Не менять старые source/tests/dependencies/БД/миграции/runner/tasks/progress.
Main V8 не запускать заново, не мигрировать и не использовать для приёмки.

## Интерфейс

`make_plan(*, target, installation_id, postgres_root, system_user,
windows_realm=None, port=None) -> PostgresPlan`: pure, без I/O/entropy/env/OS lookup.
Target macos-arm64/macos-x86_64/windows-x86_64; installation_id exact UUIDv4.
postgres_root — string absolute canonical path, UTF8<=1024, без control/NUL/dot
components; Mac без double slash/backslash, Windows drive absolute, без UNC/ADS/
wildcards/device names/trailing dot-space. Для Windows принимать оба separator,
нормализовать в uppercase-drive/forward-slash. Файловую безопасность доказывает
следующий native слой, этот parser не следует ссылкам.

system_user — OS account name, 1..256UTF8bytes, без control/NUL, slash/backslash,
double quote, @; whitespace допускается внутри, не по краям. Не regex/шаблон.
Для Windows обязателен windows_realm1..256bytes с теми же ограничениями; identity
для SSPI mapping — system_user@windows_realm, include_realm=1,compat_realm=1,
upn_username=0. На Mac realm запрещён. Native Windows caller позже получает SAM
user/domain из OS; нельзя брать произвольную identity из environment.

Mac port=None/5432, TCP выключен; socket_root детерминированно
/private/tmp/aira-pg-<installation_id.hex>, короткий private socket path вне длинного
профиля пользователя. Этот модуль его не создаёт. Windows port exact int49152..65535,
только127.0.0.1, unix_socket_directories пустой. Нет hostname/DNS/wildcard/fallback.

Frozen plan metadata (не capability): target,installation_id,postgres_root,data_dir
(root/data18),staging_dir(root/.data18.pending),socket_root(str|None),port.
`files` immutable mapping basename→bytes: server.conf,pg_hba.conf,pg_ident.conf.
server.conf пустой служебный comment; critical settings задаются argv overrides.
`initdb_arguments` и `postgres_arguments` — tuples без executable; native launcher
присоединяет проверенный bundled binary. Никаких shell strings или pg_ctl/PID files.
Repr не содержит paths/OS name/SQL/argv. Ошибки ProfileError с fixed codes
validation_error,unsupported_target,postgres_mismatch; unknown→validation_error.

## Закрытая конфигурация

initdb только в staging, UTF8/C/libc, usernameaira_local, auth-local/host=reject,
data-checksums, no-clean/no-instructions; sync остаётся включён. Никогда trust,
no-sync, group access, пароль/secret file. Частичный cluster не удалять автоматически;
publication и повтор решает следующий цикл после проверки завершения initdb.

Postgres запускается foreground с -D data_dir, внешним server.conf и explicit
data_directory/hba_file/ident_file в root. В argv: fsync/full_page_writes/
synchronous_commit on, default_transaction_read_only off, zero_damaged_pages/
ignore_checksum_failure off; ssl off; preload lists пусты; archive_mode off,
archive_command/restore_command пусты; logging_collector off, log_destination stderr,
log_statement none, log_min_error_statement panic, log_parameter_max_length_on_error0.
Bounded defaults max_connections32,shared_buffers32MB; никаких arbitrary settings
от caller. stderr будущий owner ограничивает/не публикует содержимое документов.

HBA разрешает только postgres,aira и роль aira_local: Mac local peer map=aira_owner;
Windows host127.0.0.1/32 sspi с explicit realm settings/map. Остальные local/IPv4/
IPv6 отклоняются. Ident map содержит одну exact double-quoted OS identity→aira_local;
нет regex, include, wildcard или удаления realm. Profile не создаёт DB/role/schema.

`connection(database='aira')` → detached immutable mapping libpq kwargs: dbname
(толькоaira/postgres),useraira_local,host(Unix path/127.0.0.1),port string,
connect_timeout2,application_nameaira_desktop,sslmodedisable,gssencmodedisable,
passfile=/dev/null либоNUL. Нет password, service, URI interpolation или secret reads.
Это metadata, не открытие connection. Будущий launcher обязан запускать весь Python/
PG runtime с узким env без PG*/DYLD*/PYTHON* overrides; connection kwargs не отменяют
ambient libpq service defaults самостоятельно. Supervisor URL whitelist не менять
в этом цикле; bridge следующего этапа учитывает этот контракт явно.

## Проверка наблюдения

`OBSERVATION_SQL` — fixed read-only SELECT, возвращает one JSON object с exact keys:
server_version_num(int),system_identifier(str),database,user,session_user,
in_recovery(bool),encoding,collate,ctype,settings(dict str→str).
Берёт catalog current DB, pg_control_system и только explicit pg_settings allowlist.
`check_observation(plan, observation, *, expected_system_identifier, database='aira')`
возвращает None только при: version180000..189999, nonzero canonical decimal system
identifier<=uint64 и exact expected; correct DB/aira_local current+session user;
in_recoveryFalse,UTF8,C,C; exact keys/types и совпадение каждого critical setting.
Проверять endpoint/paths/sync/preload/archive/logging/checksum guards, max_connections32
и shared_buffers4096 (32MiB при стандартном block_size8192; block_size также8192),
data_checksums=on.
Не принимать aliases/extra/missing values, bool как int, unknown versions/replicas.
Windows paths сравнивать canonical case-insensitive; другие strings exact.
Expected identifier не извлекать из того же наблюдения: будущий owner сверяет его
с собственным private cluster record/offline initialization proof. Этот pure check
не доказывает аутентичность SQL ответа или жизненный цикл процесса.

## Приёмка

Freeze/red, portable inputs/settings/immutability/injection rejection. Проверить
испорченное/чужое observation для каждого обязательного поля и отсутствие I/O.
Native Mac fixture создаёт только disposable cluster с имеющимися проверенными18.6
binaries, применяет реальные generated arguments/files, открывает peer connection,
проверяет HBA/ident parser errors, отказ чужой роли/DB, system ID/readiness, отсутствие
TCP listener и clean smart shutdown удерживаемого Popen после закрытия connections.
Это test harness, не production lifetime implementation. Никакого управления
существующим сервером через PID-файл. Windows SQL/auth/lifecycle native gate pending.

Новые test preparation defects можно исправить с записью причины, не ослабляя
assertions. Старые tests unchanged. Targeted/full/hash/mainV8snapshot/result/local
commit. Далее D05-05B native ownership/first cluster preparation, отдельно Windows,
затем schema/backup/composition. Не выдавать готовый профиль за готовый запуск.

Основания: [PG18 initdb](https://www.postgresql.org/docs/18/app-initdb.html),
[Peer](https://www.postgresql.org/docs/18/auth-peer.html),
[SSPI](https://www.postgresql.org/docs/18/sspi-auth.html),
[HBA](https://www.postgresql.org/docs/18/auth-pg-hba-conf.html),
[Ident](https://www.postgresql.org/docs/18/auth-username-maps.html),
[libpq](https://www.postgresql.org/docs/18/libpq-connect.html).
