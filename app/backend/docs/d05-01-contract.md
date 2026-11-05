# D05-01 — защищённая локальная HTTP-граница

4 ноября 2026. F02/F03/F05/F06/F11/F12, после D04-03 full4289passed/52e1473.
Один opt-in ASGI wrapper перед готовым editor API. Не desktop-установщик и не новый
frontend. Старый create_app/его маршруты/tests не меняются. Нет публикации/новой БД.

Allowed: новый src/ara/desktop/__init__.py и src/ara/desktop/access/, новые
 tests/acceptance/test_desktop_access*.py, этот contract/result/guide, очередь.
Без dependencies/migrations/runner changes; main V8 неизменна.

## Доверенная композиция

LicensedApplication(application,license_client,*,origin,session_token).
Callable inner app, точный LicenseClient из D04-03, origin ровно
http://127.0.0.1:<canonical decimal 1024..65535>, без trailing slash/credentials/query.
session_token exact bytes32. new_session_token()->bytes32 генерирует только при
явном вызове. Это временная capability запуска в RAM, не операторский секрет или
замена лицензии. Bootstrap позже передаёт её native frontend по IPC; запрещены
URL/query/cookie/log/disk. Никакой конфигурации/секретов/сети/файлов/threadstart
на import/factory. PID до обращения к runtime; copy/pickle запрещены invalid_handle.

Native server bootstrap обязан bind127.0.0.1 и proxy_headers=False, фактический
порт совпадает с origin. Эти операции/запуск UI вне этого цикла. Wrapper не запускает
и не закрывает переданный клиент/inner services; lifespan делегируется владельцу.
WebSocket всегда закрывается1008. Unknown ASGI types fail closed.

## Локальный запрос

Каждый HTTP, включая status: exact Host=127.0.0.1:port, server scope совпадает,
client IPv4 127.0.0.1 с валидным портом, scheme=http, root_path пустой. Не принимаем
localhost/DNS aliases/remote/proxy forwarded headers. Origin отсутствует(native)
либо единственный exactorigin; Sec-Fetch-Site absent/same-origin/none, но не same-site/
cross-site. Headers ≤64 и total8192bytes, имена ASCII HTTP tokens, CR/LF/NUL запрещены.
Host/Origin/X-AIRA-Session/Sec-Fetch-Site не дублируются; Forwarded/X-Forwarded-* отвергаются.
X-AIRA-Session — ровно64lowerhex, constant-time comparison. Cookie/URL не авторизуют.
При отказе inner app/лицензия/чтение body не вызываются. Fixed403 access_denied.

raw_path bytes обязателен и равен ASCII path без percentencoding; длина≤2048,
root_path пустой. Это совместимый с выбранным Uvicorn профиль, а не требование ко
всем ASGI servers. Неканонический/неизвестный path/method→404 route_unavailable.
Сначала локальная capability, потом route policy, потом лицензия. Токен удаляется
из копии scope.headers перед inner; оригинальный scope не мутирует. Никаких
автоматических redirects/CORS/OpenAPI/health/static/assets из старого dev app.

## Routes

D=/docx-documents/{nonzero canonical lowercase UUID}; S=D/editor-sessions/{UUID}.
Только перечисленные пары method/path. Finding=df-64lowerhex.

Требуют active при каждом admission:
POST D/create, D/import, D/editor-sessions, S/commands;
POST D/editor-recovery/prepare-discard, D/editor-recovery/discard;
POST D/analysis-runs, D/analysis-runs/{UUID}/retry;
POST D/analysis-preferences, D/analysis-preferences/clear-hidden;
POST D/analysis-runs/{UUID}/findings/{Finding}/visibility.

Сохранение/чтение: active либо ранее подтверждённая лицензия в этом wrapper/process:
GET /docx-documents, D, D/content, D/editor-recovery, S, S/view;
POST S/checkpoint, S/save, S/reconcile, S/close, S/working-content, S/saved-content;
POST D/editor-recovery/content;
GET D/analysis-requests/{UUID}; POST D/analysis-requests/{UUID}/stop;
GET D/analysis-runs/{UUID}, D/analysis-runs/{UUID}/result, D/analysis-runs/{UUID}/review;
GET D/analysis-result, D/analysis-review, D/analysis-preferences.

Нет разрешающих wildcard prefix/методов. Остальные routes (включая legacy /documents,
/runs,/me,/workspace,/docs,/openapi.json, DOCX PUT content/text-edits/paragraph-commands/
draft/view) дают404 даже с active. Старый app без wrapper сохраняет прежнее поведение.

Ever-verified flag устанавливается только успешным require_active(), в том числе
при status. Новый wrapper начинает false; сохранённая activation identity этого
флага не даёт. Без первой проверки никакие данные недоступны. После expiry/failed
retry доступны только перечисленные сохранение/чтение/Stop. Closed LicenseClient
запрещает и их. Стандартные registry scope/CAS/revisions/download guards остаются.
Новые команды редактирования/create/import/open/анализ/retry/hide не принимаются.

Admission — момент вызова require_active() перед inner dispatch. Уже принятый
ограниченный HTTP-запрос/анализ может завершить транзакцию после expiry; нет
прерывания halfway COMMIT. Сохраняется принятый backend текст. Несинхронизированный
DOM/IME buffer будущего frontend требует его собственного flush/local rescue;
этот цикл не объявляет отсутствующий UI защищённым от потери данных.

## License endpoints

GET /desktop/license без body/query. POST /desktop/license/activate exact
{license_key:str}; POST /desktop/license/verify exact {}. Тот же local token
обязателен. POST→LicenseClient.start→202 snapshot, GET→200 snapshot.
JSON schema_version=aira-desktop-license/1, phase,error_code,license_id|null,
expires_at_ms decimalstring|null,retry_available bool,preservation_available bool.
Никаких ключей/device ID/remote origin/nonce/permit. Preservation flag true только
после successful require_active и пока client не closed, не офлайн-разрешение.

Body≤1024bytes/32frames/3s; четыре nonqueued body slots. GET body0; POST JSON UTF8,
identity encoding; duplicate/extra fields/nonfinite/badUTF8/ContentLength mismatch/
query отвергаются. Metadata/valid start короткие; не выполняют blocking network.
Ошибки фиксированные code/message: validation_error422, unsupported_media415,
request_too_large413, request_timeout408, local_busy503, route_unavailable404,
access_denied403, invalid_handle500, local_error500; ClientError сохраняет fixed code/status.
Текст server/network/OS exceptions никогда не отражается. Ошибка не закрывает
LicenseClient и не стирает документы. Failed POST не отправляет key в inner.

Все HTTP ответы (включая inner errors) no-store/nosniff/no-referrer; убрать inner
Access-Control-* headers. Перед началом ответа unexpected error→fixed local_error500;
после начатого ответа закрытие соединения с fixed exception, без второго status.
Не логировать raw input/token/key, не добавлять access logging.

## Приёмка

Freeze/red прежде source. Independent route matrix: active/preservation/new/closed,
unknown/new methods/encodedpaths; headerduplicates/origin/host/client/forwarded/token
блокируют доbody/client/inner. Strictlicensebody/status/activation/check/doubleclick/
failure/restart/timeout/admission slots; strippingheaders/lifespan/WebSocket/fork.
Actual create_app на disposableV13: create/open/commands→expiry→denynewwork→checkpoint/
save/working+saved export без потери bytes; acceptedanalysisfinish/Stop/read остаются,
новый анализ/retry не проходит; original DOCX и storage unchanged при отказе.
Вспомогательные fixture device/clock/transport явно учебные, реальный ML не заявляется.
Старые source/tests/assertions не меняются. Ошибки подготовки новых tests можно
исправить с документированной причиной без ослабления приёмки. Targeted/full/hash/
mainV8 snapshot/result/localcommit. UI/bootstrap/model/packaging/TLS/Windows release
остаются отдельными циклами/gates.

Основание transport: [ASGI HTTP scope](https://asgi.readthedocs.io/en/latest/specs/www.html),
[Fetch metadata](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site).
