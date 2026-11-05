# D04-03 — клиент онлайн-проверки лицензии

4 ноября 2026. F03/F02, после D04-02 full4195passed. Один клиентский компонент:
идентичность устройства, сохранение публичной активации, HTTPS-проверка и допуск
только на текущий запуск. UI/desktop bootstrap подключается отдельным циклом.

Allowed: новый src/ara/licensing/client/, новые tests/acceptance/test_licensing_client*.py,
этот contract/result/guide, очередь и уточнение фактического статуса F03. В pyproject.toml
перенести существующий httpx>=0.27,<1 из dev в runtime; locked0.28.1 не обновлять.
Старые source/tests/migrations/runner неизменны, основная БД остаётся V8.

## Публичные операции

ActivationIdentity(license_id UUID,device_id dv1-64lowerhex), frozen; ActivationStore(root)
с абсолютным Path без '..', конструктор без I/O. load()->identity|None; save(identity)->None.
Файл license-activation.json: точные schema_version=aira-license-activation/1,license_id,
device_id; canonical JSON<=1024bytes, duplicate/unknown fields запрещены. Ключ/nonce/срок/
permit не сохраняются. Отсутствие файла/папки→None, повреждение→activation_store_error.
После успешной explicit activation допустима замена повреждённого regular файла.

Папка создаётся явно при save, parent должен существовать. POSIX owner текущий UID,
нет group/world write; root directory не link, file regular/nlink1/owner, не link/reparse.
Anchored dir_fd/O_NOFOLLOW, read O_NONBLOCK и bounded read1025. Temp exclusive0600,
полная запись/fsync/close, replace в той же папке, fsync directory. Ошибка оставляет
старый либо целый новый файл при неопределённом результате после rename; не трогает
документы. Windows lstat/reparse checks, fsync file, MoveFileExW(REPLACE_EXISTING|
WRITE_THROUGH), без copy-across-volume. Windows parent — доверенная app-owned папка;
не обещаем защиту от same-user parent swaps/сбой-питания без native release gate.

read_device_id()->dv1 digest: macOS IOKit IOPlatformExpertDevice/IOPlatformUUID через
lazy ctypes, CFString type/bounded64byte UTF8, finally release acquired CF/service.
Windows GetSystemFirmwareTable('RSMB',0), two-call exact size8..1MiB. RawSMBIOSData
length exact, version>=2.6, bounded formatted+doubleNUL string scan, один type1 UUID
at offset8 (length>=24), UUID(bytes_le=...), nil/allFF reject. Type127 обязателен,
после него данные игнорируются по SMBIOS end-of-table; malformed before end rejects.
parse_smbios_uuid(data) pure helper. Raw UUID нигде не логируется/сохраняется/передаётся.
Без shell subprocess, hostname/MAC/random fallback. Unsupported platform/native failure
→device_unavailable. Native Windows отдельно skipped на macOS.

## HTTPS

HttpsTransport(origin) inert; origin только HTTPS ASCII DNS/IP host и optionalport,
без credentials/query/fragment/nonroot path. execute(request,checkpoint)->bytes:
checkpoint до/после I/O и каждого chunk. Fixed POST /license/v1/activate|check.
HTTPX Client на одну попытку: verify=True,trust_env=False,follow_redirects=False;
limits1connection/0keepalive; timeout connect/read/write3s,pool0.5s. JSON content-type,
Accept application/json,Accept-Encoding identity. Reject redirects/compression,
nonJSON, declared/actual body>8192; iter_raw1024 не распаковывает входной поток.
200 возвращает bytes после strict grant decode. Known error exact code/message shape
и соответствующий HTTP status→fixed ClientError, удалённый message игнорируется;
неизвестные/испорченные ответы→invalid_response. TLS/DNS/socket failure→network_unavailable.
Нет скрытого retry, proxy/env/trust injection в обычном transport. Injected fixtures
допустимы только явным trusted construction и не доказывают production TLS.

## Процесс и состояние

LicenseClient(origin,store,*,device_provider=None,clock=None,transport=None), inert.
Default clock — существующий DarwinClock/WindowsClock с учётом сна, без wallclock.
Все методы проверяют PID до mutex; runtime не копируется/не сериализуется.
start(key=None)->snapshot неблокирующий по файловым/сетевым/native identity операциям;
clock read синхронный короткий, native lazy initialisation вне state lock. Новый nonce
32bytes на попытку. Тот же intent пока worker жив→тот же state; иной→client_busy.
При новом start прежний permit очищается. Один daemon thread максимум, новый запрещён
пока старый жив, включая timeout/close; DNS может пережить socket timeout, жёсткого
OS kill не обещаем. Worker владеет HTTP client и закрывает его на любом исходе.

Рабочая последовательность: device→identity (check only)→HTTPS→D04-01 authorize_start
→save identity (activate only)→require_access→publish. Нет identity/key→activation_required
без сети; несовпадение устройства→device_mismatch без сети. На timeout15s/clock failure/
close результат инвалидируется. Наблюдаемый cancel запрещает дальнейший save; уже
начавшийся atomic save может завершиться, но поздний доступ не выдаётся. Storage error
не даёт доступ; повтор ключа серверу сохраняет исходный срок. Check identity не пишет.

view()->frozen Snapshot(phase,error_code,license_id,expires_at_ms,retry_available).
Phases new/activation_required/checking/active/failed/expired/closed. view и
require_active()->LaunchPermit повторно проверяют clock/deadline. На ошибку clock
клиент fail closed. require_active без permit→access_denied, при expiry→license_expired.
Snapshot не содержит ключ/device UUID/ответ сервера. close()->None неблокирующий,
не даёт resurrect из late result; retry false пока worker не drained. Closed нельзя
перезапустить. Desktop позже закрывает новые protected actions, но сохраняет уже
набранный текст/экспорт и завершение ранее принятой модели. Здесь UI не меняется.

Все ошибки фиксированы: ClientError(code) с локальным message/status, неизвестный
code→client_error; исключения портов не попадают в message. Явно injected fixture ports
clock.now_ns(),device_provider(),transport.execute(request,checkpoint),store.load/save.
Runtime checkpoint ограничивает весь запуск, включая hardware/storage,15s. PID/fork,
copy/pickle rejects invalid_handle. Нет filesystem/network/secret I/O на import/factory.

## Приёмка до реализации

Synthetic SMBIOS byteorder/versions/nil/FF/duplicate/truncation/end/limits; fake Mac CF
cleanup и настоящий macOS digest stability без вывода identity. Windows native отдельно.
Store reopen/no-key/strictJSON/links/partial writes/fsync/rename unknown-ack. HTTP TLS
configuration/endpoint/status/body/redirect/compression/sanitization/close/cancel.
Runtime first activation/restart/no offline fallback/expiry/sleep/clock/nonce mismatch/
double click/busy/timeout/late result/close/save failure/PID/constructor inertness.
Связка с настоящим серверным core+HTTP на disposable PG через явно fixture transport.
Старые assertions неизменны; ошибки подготовки новой приёмки можно исправить с
документированной причиной, без изменения проверяемого поведения. Targeted, full,
hash snapshot,mainV8 snapshot,результат,локальный commit. Production HTTPS и Windows
native остаются отдельными внешними release gates.

Источники native API:
- [Apple IOKit ownership](https://developer.apple.com/documentation/iokit/1514535-ioservicegetmatchingservice)
- [Microsoft firmware](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getsystemfirmwaretable)
- [DMTF SMBIOS2.6, §3.3.2.1/3.3.44](https://www.dmtf.org/sites/default/files/standards/documents/DSP0134_2.6.0.pdf)
- [Microsoft MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)
