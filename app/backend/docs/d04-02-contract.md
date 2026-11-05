# D04-02 — сервер лицензий: PostgreSQL и HTTP

4 ноября 2026, после D04-01 full4156passed (8f5aacd). F03, licensing-design.md. Один отдельный
серверный компонент: выдача, one-device activation, startup check. Не запускать
публичный сервис/не создавать production keys/не мигрировать основную V8.

Allowed новый `src/ara/licensing/server/` (_models,_schema,_storage,_http,_config,
__init__,__main__), новые tests/acceptance/test_licensing_server*.py и docs
contract/result/guide/queue. Старый licensing core и другие source/tests/migrations/
dependencies/runner неизменны. Использовать имеющиеся FastAPI/SQLAlchemy/psycopg.

## Отдельная БД

Две public tables только в явно подготовленной серверной БД:
`aira_license_schema(id smallint PK CHECK id=1,revision integer NOT NULL CHECK>0)`;
singleton id1/revision1. `aira_licenses`: license_id UUID PK, key_digest VARCHAR64
unique/notnull/lowerhex, duration_seconds BIGINT positive bounded D04-01,
enabled BOOLEAN notnull, created_at_ms BIGINT bounded epochms, device_id VARCHAR68
nullable/dv1-lowerhex, activated_at_ms/expires_at_ms BIGINT nullable. Named checks
enforce bounded timestamps, all-three-null-or-all-set, expiry=activation+duration*1000,
activation>=created_at. No plaintext keys, nonce/grant history, user/doc fields.

`initialize_database(engine)` explicit transactional setup. PostgreSQL18 only,
finite SQL timeouts and database advisory transaction lock. Empty public relations
→create two tables/marker atomically. Existing exact table/column type/nullability/
named constraint/PK/unique structure and marker1→read-only success. Unknown/partial/
foreign structure or wrong marker→license_schema_unavailable; never repair/drop/adopt.
No automatic initialization/migration from runtime, HTTP factory or imports.

`ServerRuntime(engine,pepper,clock_ms=None)` frozen; engine/pepper/clock repr=False.
Explicit PostgreSQL SQLAlchemy Engine and bytes32..64 pepper; injected clock only
trusted construction/tests, default database clock_timestamp rounded down to ms.
Runtime doesn't own caller engine. Config-created engine pool_size2/max_overflow0,
pool_timeout0.5, connect_timeout5, hide_parameters; creator/CLI disposes it explicitly.
Each storage transaction SETLOCAL lock_timeout500ms,statement_timeout2s,
idle_in_transaction_timeout2s,transaction_timeout5s; schema marker check before data.

## Operations

`issue_license(runtime,*,license_id,key,duration_seconds)` explicit operator API.
Validate key/core inputs before SQL; HMAC lookup only. INSERT ON CONFLICT DO NOTHING,
then lock/read by caller UUID. Same UUID/hash/duration→current record, never reset
active binding/disabled flag/times; mismatch or duplicate hash under another UUID
license_conflict409. Concurrent same key/UUID create one record, original creation
time kept. No HTTP issuance/admin endpoint. `get_license(runtime,*,license_id)`
returns public detached LicenseRecord; no key/digest. `set_enabled(...enabled)`
trusted operator action, bool only, atomic lock, does not change activation/time.

`process_request(runtime,request)` validates canonical StartRequest. Activation:
HMAC row lookup FORUPDATE; check: UUID row lookup FORUPDATE. Missing row invalid_license403.
Read trusted time after lock, require no earlier than creation; D04-01 activate/check;
write first binding only, construct encoded grant, return only after COMMIT.
One key raced by two devices→one winner. Replay same device never extends.
Unknown COMMIT→safe503; retry resolves persisted state. Check never activates or
writes entitlement. Disabled/expired/device mismatch use fixed D04-01 errors.
Finite SQL failures license_storage_unavailable503; corrupt rows license_storage_error500
or core invalid_record500, no SQL/input repr in returned errors. No automatic retries
that change intent. Never send documents or start ML/local editor.

## HTTP

`create_license_app(runtime)` inert optional independent FastAPI app; default editor
app not changed. Only POST `/license/v1/activate`, `/license/v1/check`. Request
operation must match route. HTTPS scheme required; production reverse proxy must
be explicitly trusted, plaintext request returns400 https_required. No redirects,
CORS or automatic auth/account/billing endpoints. OpenAPI method available to tests,
docs/openapi HTTP routes disabled. Input key only in JSON body, never query/path.

Strict JSON max8192bytes, no query, JSON UTF8 content type, bounded body read5s and
max128 frames, content-length guards. Global4 nonwaiting admission slots include
body/SQL;503 license_busy on saturation. SQL in shielded AnyIO worker with4 limiter;
cancelled caller cannot interrupt a half COMMIT. All outputs/errors/404 no-store;
errors fixed code/message, no reflected input or traceback. Body timeout408,
oversize413,unsupported media415,validation422. Response200 canonical core grant;
nonce echo only from validated request, time and license facts server-owned.

## Explicit operator startup

Settings from ~/secrets.env only when explicitly loaded: AIRA_LICENSE_DATABASE_URL,
AIRA_LICENSE_PEPPER (hex32..64bytes); AIRA_LICENSE_ISSUE_KEY only for explicit issue.
No scanning other secret files/env/keychain, no plaintext repr/logs. Test settings
injected as memory mapping. `python -m ara.licensing.server init|serve|issue|disable|enable`:
init explicit setup; issue UUID/duration CLI args are public, key only secrets.env;
serve loopback127.0.0.1 with chosen bounded port, trusted proxy only127.0.0.1 and
access logs disabled. CLI never prints key/pepper/database credentials, fixed errors.
No auto-init while serving. Operator API/CLI not a public admin service.

## Acceptance before implementation

Isolated empty_pg_engine for dedicated schema; repeat/rollback/foreign/partial/schema
guards; SQL constraints and no plaintext columns; main V8 unchanged. Issue normalization/
idempotency/conflicts/disabled preservation; simultaneous activation two devices,
same-device retry, exact expiry, not-activated check, clock rollback; before/afterCOMMIT
failure and no renewal; no source/global secrets I/O. HTTP strict inputs/limits/
operation/HTTPS/no-store/no echo; public OpenAPI;4-slot body/SQL admission and transport
timeouts; startup/config/CLI safe output with injected synthetic secrets only.
Frozen core54 cases unchanged; targeted core+server then full/hash/snapshot/result/
localcommit. Real deployment/TLS end-to-end and desktop integration remain separate.

Уточнение public settings API: load_settings(values=None,for_issue=False), create_runtime(settings). Mapping только для явной тестовой/доверенной инъекции; default читает ~/secrets.env. Settings.issue_key=None без for_issue. CLI main(argv)->exit code, parser errors не отражают argv; serve port1024..65535. initialize_database возвращает None; issue/get/set_enabled возвращают LicenseRecord. Existing frozen tests/старые assertions не менять; ошибки подготовки новой приёмки исправлять с документированием, сохраняя её смысл, до финального gate.
