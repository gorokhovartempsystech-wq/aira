# D04-01 — pure лицензия и подтверждение запуска

4 ноября 2026. F03, [дизайн](licensing-design.md), после E4C2 full4102passed.
Allowed новые `src/ara/licensing/{__init__,_models,_policy,_wire,_startup}.py`,
`tests/acceptance/test_licensing_policy.py`, docs contract/design/result/queue и
техническое уточнение F03. Старые source/SQL/tests/dependencies/runner/tasks/progress
не менять. Stdlib, без I/O, чтения clock/RNG/config/secrets, процессов/потоков.

## Public API

Frozen `LicenseRecord(license_id:UUID,duration_seconds:int,enabled:bool=True,
device_id:str|None=None,activated_at_ms:int|None=None,expires_at_ms:int|None=None)`.
UUID exact nonzero; device dv1-+64lowerhex; timestamp exactint0..253402300799999,
duration exactint1..MAX_EPOCH_MS//1000; expiry=activation+duration*1000 в диапазоне.
Три activation поля все None либо все заполнены. Каждая операция повторно
проверяет DTO после возможного object.__setattr__, отдаёт detached record.
`activate(record,*,device_id,now_ms)` привязывает один раз; повтор сохраняет срок.
`check(...)` требует прежнюю активацию. now<activation clock_unavailable,
expiry boundary denied, disabled/другое устройство denied. Нет hidden renewal.

`normalize_key(value)` → AIRA-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX (ASCII hex upper),
принимает lower case и ASCII whitespace по краям, raw≤128. `key_digest(key,pepper)`
HMAC-SHA256 canonical ASCII, pepper exactbytes32..64, возвращает64lowerhex.
`device_fingerprint(platform,hardware_uuid)` принимает exact macos/windows и
canonical nonzero/non-all-ones UUID string; SHA256 домен+платформа+UUID → dv1-digest.
Точные hash bytes: b'aira-device-v1\0'+platform ASCII+b'\0'+UUID.bytes.
Никакого hardware/RNG чтения. Ключи и pepper не отражаются в repr/errors/logs.

Frozen `StartRequest(operation,device_id,nonce,license_key=None,license_id=None)`;
operation activate/check, nonce64lowerhex; license_key repr=False. Activate требует
только key, check только UUID. `encode_request/decode_request` bytes schema
aira-license-request/1; exact поля schema_version,operation,device_id,nonce и
license_key либо license_id. Encoder canonical JSON, decoder допускает порядок/
whitespace, но не duplicate/unknown/missing/nonUTF8/nonfinite/oversize/deep traps.
Бюджет8192bytes, request invalid422. Raw values не попадут в сообщения ошибок.

Frozen `LaunchGrant(operation,license_id,device_id,nonce,activated_at_ms,
checked_at_ms,expires_at_ms)`, activation<=check<expiry. `make_grant(record,request,
*,now_ms)` требует check; record уже активирован вызывающим сервером, check UUID
совпадает. `encode_grant/decode_grant` schema aira-license-grant/1, поля DTO+schema,
UUID/времена canonical strings,≤8192bytes; ключа в grant нет. Grant invalid502.
Несовпадающий check UUID при make_grant — invalid_record500 (не тот server record).

`authorize_start(request,grant_data,*,started_ns,received_ns)` проверяет grant,
operation/device/nonce и license UUID при check. Caller обязан передать ответ
текущего проверенного HTTPS: это не signature verifier/offline activation.
Clock exactints0..2^63-1, received>=started, elapsed<=15_000_000_000ns.
Deadline=started_ns+(expires_at_ms-checked_at_ms-1)*1_000_000; received>=deadline
даёт license_expired. Frozen `LaunchPermit(license_id,device_id,received_ns,
deadline_ns,expires_at_ms)` без key/nonce; deadline может быть Python bigint.
`require_access(permit,*,now_ns)` перепроверяет metadata, now>=received и
now<deadline. Разрешение будущий клиент держит только в RAM; F3 добавит ownership
текущей попытки, уникальные nonce и continuous OS clock.

`LicenseError` имеет фиксированные code/status/message, безопасные str/repr.
validation_error422: caller input; invalid_record500: record/permit corruption;
invalid_response502: bad grant/mismatch; not_activated403,license_disabled403,
device_mismatch403,license_expired403; clock_unavailable503,verification_timeout503.

## Приёмка

Независимые cases: длительности/expiry boundary/replay/device/disabled/inactive;
частичные и несогласованные records, строгие типы/overflow/mutated DTO;
canonical key/HMAC по отдельному stdlib oracle; domain-separated device digest;
wire canonical bytes/roundtrip и malformed duplicate/extra/deep/nonfinite/size;
nonce/device/license/operation mismatch, сетевой интервал/1ms truncation/поздний
ответ/regressed clock, wall-clock independence, immutable permit; inert imports
и отсутствие I/O. Freeze/red до source, targeted/full/hash/mainV8 snapshot/result/
локальный commit; затем отдельный D04-02, не ждать model pack/frontend.
