# D05-06A — explicit owned SQL bridge

4 ноября 2026, после D05-05D2/0ea8b9e. F02/F11/F12: редактор и supervisor используют
одну подготовленную локальную БД, проверяя фактическое соединение и его завершение.
Mac wiring выполняется первым ради native сквозной приёмки. Windows, настоящий
ML pack, frontend, HTTP composition/build остаются обязательными отдельными этапами.

Allowed новые `src/ara/desktop/database/`, `tests/acceptance/test_desktop_database*.py`,
этот contract/result/guide/queue. Два прежних source файла допускают только additive
bridge: `docx_analysis_worker/supervisor/database.py` и `supervisor/runtime.py`.
Legacy DatabaseSettings/URL whitelist/pool/options/factories остаются совместимыми.
Старые tests/migrations/остальной source/dependencies/runner/tasks/progress unchanged.
Main V8 не мигрировать и не использовать как owned пользовательскую БД.

## Интерфейс и владение

`bind_database(home,cluster,*,schema)` — explicit metadata-only factory. Требует exact
живые DataHome/ClusterRuntime/SchemaPreparation handles, успешный D1 receipt, совпадение
Home-derived IDs и actual cluster identity. Не принимает handmade receipt вместо
handle, URL, секреты, arbitrary connector или development UUID. Не открывает SQL,
файлы/сеть, не меняет schema/identity/Fence. Factory выдаёт process-local DatabaseSource
и берёт strong process claim на Home; второй открытый source — database_busy.

Source: `document_runtime()`, `settings()`, `view()`, `shutdown(timeout=5)`.
DocumentRuntime с Home user/project и lazy Engine создаётся без native connection.
Settings — frozen DesktopDatabaseSettings с repr-hidden issued source. Dataclass
replace оставляет тот же live source. Это не самостоятельный скопированный доступ.

`DatabaseView` frozen: phase,error_code,connections,connecting,resources_pending.
Фазы ready/stopping/closed/failed; ready здесь означает metadata binding, а не
сетевой healthcheck. Пока claim открыт, resources_pending=True даже при counts0;
после known shutdown — closed/False. Unknown native cleanup — failed/pending,
error_code cleanup_unknown и strong claim/raw objects до выхода процесса.

No copy/deepcopy/pickle Source; PID проверяется до любого inherited mutex. Registry
также проверяет PID до собственного lock. Handles/ошибки не печатают paths/SQL/
пользовательский текст. DatabaseError fixed codes validation_error,invalid_handle,
database_busy,database_unavailable,database_mismatch,cleanup_unknown; unknown code
становится database_unavailable. Timeout exact int/float finite0..5, bool запрещён,
в том числе huge int отвергается штатно, без OverflowError.

Borrowed Home/cluster/schema живут дольше Source. Порядок composition: закрыть вход
HTTP и дождаться принятых запросов, завершить supervisor, source.shutdown, затем PG
и Home. Source не отменяет, не закрывает и не rollback-ит уже переданную caller
transaction ради Stop. Shutdown запрещает новые connects и ждёт known возврата
своих DBAPI connections; False остаётся ожиданием, без force kill/retry numeric FD.
Если shutdown пришёл во время соединения/проверки до передачи caller, own connection
закрывается один раз, caller не получает новый доступ. Клиентский SQL/COMMIT внутри
уже полученного connection остаётся разрешённым до его возврата.

## Lazy engines и supervisor

Desktop engines используют NullPool: DBAPI закрывается при каждом возврате, idle
SQL connections нет. Документных live+inflight максимум4, каждый supervisor lane
admission/control/publication максимум1; занятость даёт database_busy без очереди.
Это технические concurrency limits текущего desktop, не продуктовый лимит документов.

`supervisor.database.create_engines` узнаёт только новый exact settings type и
создаёт три source-bound engines. Legacy path не меняется, его URL whitelist не
расширяется. `_create_supervisor` принимает новый type, проверяет Home user/project/
installation и root ровно Home.analysis; dataclass replace сохраняет source.
Публичные opaque/review fixture factories уже передают settings и не меняются.
Fixture остаётся явно fixture; готовность реальной модели не утверждается.

Engine creation/inert import не читает environment/secret/settings и не делает SQL.
Нет глобального monkeypatch create_engine, implicit load_settings или замены API.
Source tracks actual native connections independently: SQLAlchemy может поглотить
ошибку DBAPI close, а NullPool.dispose не доказывает отсутствие borrowed connection.
Supervisor closed отдельно от Source cleanup; composition обязана проверить оба.

## Каждый native connect

1. PID/live handles/claim/role/Stop проверить, занять ограниченное inflight место.
2. Known LIBPQ_ENV reject по наличию перед native IO; значения не читать.
3. Explicit Cluster.connection('aira') kwargs: exact owned socket/port/user/db,
   connect_timeout2, application_name, passfile=/dev/null, sslmode/gssencmode disable.
   Нет URL interpolation/default .pgpass/settings/env/secrets/fallback.
4. Tracked psycopg.Connection class, strong raw registration до проверок. Document
   options statement60s/lock1s/synchronous_commit on/search_path public,pg_catalog.
   Supervisor сохраняет существующие bounded OPTIONS плюс explicit search_path.
5. На actual raw connection readonly проверить PG18/systemID/databaseOID/aira/
   aira_local session+current user/synchronous_commit/primary, schema revision13,
   единственные Home user/project и installation binding analysis fence. Fence
   phase/owner_epoch здесь не сбрасывать; lifecycle остаётся у supervisor.
6. Rollback собственной read probe, повторная live/Stop проверка; только потом
   выдать connection SQLAlchemy. Нельзя принять заменённую БД по старой metadata.

Этот bridge не повторяет всю D1 shape validation при каждом запросе и не обещает
защиту от произвольного ручного SQL superuser изменения; доверенная composition
выполняет D1 до открытия приложения и не запускает миграции параллельно.

Native close wrapper сначала фиксирует попытку, затем один вызов driver close;
положительный результат и closed=True дают known release. Исключение после driver
закрытия всё равно unknown: psycopg ставит _closed до pgconn.finish, поэтому один
boolean не доказывает завершение. Нельзя повторно close через raw/числовой handle;
сохранить strong raw/claim и fixed error. PID-check до wrapper mutex/native operation.
Connect OperationalError до получения connection трактуется как known failure
драйвера; иной неизвестный исход native creation удерживает inflight/claim. Probe
failure закрывает только своё ещё не выданное соединение. Native diagnostics наружу
не передаются. Нормальный отказ connect не выполняет восстановление/DDL.

## Приёмка

Freeze/red. Inert factory/settings/engine, PID/copy/foreign/dead/unprepared/duplicate
binding и invalid timeout. На новом temporary Mac PG: D1→source→actual import/read
DOCX/three supervisor lanes с теми же IDs; native semantic fixture analysis через
неизменённую public factory, result fixture и exact source preserved/reopen.
Environment reject до connect; readonly actual OID/revision/identity mismatch,
включая rename old synthetic DB + replacement empty DB с сохранением старого DOCX.

Удержать synthetic write transaction: source.shutdown False/new connects denied;
COMMIT/known close сохраняют текст и дают closed, затем новый source читает то же.
Поломка driver.close после настоящего finish в отдельном процессе остаётся pending,
несмотря на raw.closed True и SQLAlchemy suppression; no second close/rebind.
Concurrency caps и Stop во время до-клиентского connect/probe. Новые test preparation
fixes допустимы с записью причины и сохранением assertions, старые tests unchanged.

Required full `bash scripts/check.sh`, final hash manifest/previous681 unchanged
кроме двух разрешённых additive supervisor files, readonly mainV8 snapshot/result/
local commit. После — следующий цикл desktop composition, без остановки по уже
данной команде Никиты. Native Windows/реальные модель и UI/release gates отдельно.
