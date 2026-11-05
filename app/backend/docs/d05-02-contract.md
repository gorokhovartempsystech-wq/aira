# D05-02 — владение локальным сервером

4 ноября 2026. F02/F03/F11/F12, после D05-01 full4411passed/68ef319.
Один native host component для существующего ASGI app + LicenseClient.
Allowed: новый src/ara/desktop/server/, tests/acceptance/test_desktop_server*.py,
этот contract/result/guide/queue. Старые source/tests/dependencies/migrations/runner
не меняются. Не запускаем main PG/model/UI, не публикуем сервис. Runtime зависимости
уже locked: uvicorn0.53.0,h110.16.0,anyio4.15.1. Основная БД V8 неизменна.

## API и владение

LoopbackServer(application,license_client): callable app, exact LicenseClient.
Конструктор без I/O/entropy/native calls/threads/сети/настроек. start()->HostView,
view()->HostView, connection()->LocalConnection|None, shutdown(timeout=0..5)->bool.
HostView frozen: phase new/starting/ready/stopping/closed/failed,error_code|null,
resources_pending bool,clean_shutdown bool. Connection frozen: origin,session_token
exact bytes32 repr=False; отдавать detached copy толькоready. Токен неURL/log/file.
new_session_token/лицензия старого цикла неизменны. HostError(code) fixed status/message;
unknown→server_error. PID проверяется до любых mutex; copy/pickle запрещены.

Владение передаётся при start после process-local claim app/client identity. На
одних объектах нельзя одновременно запускать два host. До claim чужой client не
изменяется: shutdown(new) закрывает только пустой host; ownership conflict не
закрывает другой сервер. Client должен быть new при start, иначеvalidation_error
без запуска. После claim/bootstrap worker start() запускает client.start ровноодинраз.
Последующие start того жеhost возвращают его состояние, не перезапускают terminal.

Один daemon thread+asyncio loop наhost, native socket IPv4 127.0.0.1:0; portнеугадывать.
Фактический canonicalorigin передаётся D05-01 wrapper, новый RAMtoken32bytes.
Socket non-inheritable, без REUSEPORT/REUSEADDR; Windows EXCLUSIVEADDRUSE.
Никаких subprocess/shell/global installs/config/secret reads. Все OS/I/O операции
вworker вне state/global locks. Подписьready означает HTTP+lifecycle, не model/license.
Если активациинет/сетьнедоступна, licenseAPI остаётся доступен, documentsguard закрыт.

## Lifespan

Host сам ведёт один ASGI lifespan2.0 task в том жеloop, чтоHTTP; Uvicornlifespan=off.
Startup.complete обязателен перед приёмомHTTP. Это strict lifespan-on profile;
unsupported/exception/failed не переключаются в compatibility mode. Сырыеfailure
messages/исключения не печатать, толькоfixed lifespan_error. State namespace создаётся
пустым; каждому HTTP scope передаётся shallow copy. Владелецapp сохраняеткомпоненты
черезсвойlifespan; hostнеугадывает engines/supervisors илипользовательские папки.

Startup wait15s; timeout/stop invalidates ready, но не отменяет lifecycle task с
возможной записью. resources_pending остаётсяtrue, повторновыйworkerне создаётся.
Поздний startup.complete получает shutdown, а не HTTPready. Startup.failed:
не посылать shutdown, дождаться завершения app task/егоfinally. Неправильный ack,
ранний return/exception,shutdown.failed→lifespan_error. Failedcleanup не выдаёт
clean_shutdown; app/client остаются quarantined для повторногоhost в этомпроцессе.
Clean lifecycle/release разрешает новыйhost с подходящими новыми компонентами.

## HTTP и body envelope

Композиция: shutdown fence → LicensedApplication → bounded body/state injection → app.
License routes обрабатывает D05-01; headers/capability/license проверяются доbody.
Уже принятыйHTTP запрос может завершиться послеexpiry (D05-01). НовыеHTTPпослеstop
даютfixed503 server_stopping доbody; не создают ещёпопытку активации. WebSocketdisabled.

Uvicorn HTTP=h11,ws=none,lifespan=off,proxy_headers=False,access_log=False,workers1,
reload=False,server_header=False,date_header=False,timeout_keep_alive5,
timeout_graceful_shutdown=None,limit_concurrency16/backlog32. No force_exit.
Запуск с явно переданным owned socket. Никакого fixedport/conflict takeover.
Настройки логирования только в explicit startup; не включать raw exception logs.

До innerHTTP прочитать body целиком с существующими bytecaps:
import DocxLimits.max_archive_bytes=32MiB; editor commands8MiB; otherPOST64KiB;
create/GET0. До32768 frames и15s ожидания поasyncio timer; этоттаймер не определяет
сроклицензии (D04continuousclock прежний). ContentLength/TransferEncoding/encoding
противоречия отвергаются; не изменять media/query/data. Completebody replay exactly
once затем receiveделегируется для disconnect. Timeout/disconnect/size/frame failure
доinner→fixed408/422/413, безSQLeffects. Два ordinary slots иодин dedicatedStop
безочереди, удерживаютсядоокончанияresponse; busy503. License endpointsнезависимы.

## Закрытие

shutdown(timeout exact int/float finite0..5,неbool) ставитstop/fence, убираетconnection,
не ждётподlock. Caller ждётнебольшеtimeout; еслиworker/lifecycle/HTTP ещёживы→False,
stopping/failed+resources_pending. Повтор shutdown тольконаблюдает/дожидается тотже
процесс, не создаёт новый. Нет насильственной отмены принятойHTTP/COMMIT; послеdrain
закрыть listening/owned socket иsend lifespan.shutdown, дождатьсяack+taskcompletion,
закрыть LicenseClient. Покаdrainpending, app resources нельзя объявлять освобождёнными.

Прианомальном serveexit попытатьсягрейсфулdrain через publicServer.shutdown с
lifespanOff, послеэтогособственныйappshutdown, бездвойногоlifecycle. ЛюбыеSystemExit/
обычные ошибкиоборачиваютсяfixedserver_error/lifespan_error; не отражатьключ/URL/body.
Еслиappcleanupfailed, thread/socketмогутужеосвободиться, ноclean_shutdownFalse и
shutdownFalse; повторноappне запускать. Никогда не объявлятьclosed/clean по одному
таймауту caller. Ошибка bind доappstartup освобождаеттолькоownfd/client, безappcleanup.
Приудалении процессом/OS гарантийне добавляем; клиентский DNSworkerможетдоживатьпосле
LicenseClient.close поD04-03. resources_pending здесь про hostthread/socket/lifespan,
а не обещание killDNS/model/PG. Полныйproduct shutdown долженпредварительно flush
редактор; hostне сериализует непереданныйUIbuffer/не делаетавтосохранение заfrontend.

## Приёмка

Freeze/red доsource. Factoryinert/errorsPID/copy/tokenrepr; actual ephemeralHTTP,
newstartuplicensecheck/capability; onerepeatedstart; app/client ownership. Lifespan
state same-loop/shallowcopy/order, failure sanitization, late startup timeout/stop,
shutdownack/failure/hang; port/threadcleanup иnone connectionпокаstopping. Native
Windows socket option иреальныйWindows gate отдельноотMac/portablefixtures.
Bodyexact replay/caps/frames/deadline/disconnect beforeinner;2ordinary+Stop lane,
licensepollнеblocked; отменаprebodyне mutatesSQL. AcceptedHTTPdrains безcancellation,
shutdownFalseuntilreleased; controlledreal editor save продолжаетсяприstop ипосле
полногоshutdown reopenпоказываетподтверждённыйDOCX. DisposableDB, mainV8 unchanged.
Старыеassertions/sourceне менять. Ошибкиподготовкиновыхtests допустимоисправлятьс
записьюпричиныбезослабленияприёмки. Targeted/full/hash/snapshot/result/localcommit.
UI,PGbootstrap/migrationbackup,modelpackage/composition/installers отдельны.

Primary: [ASGI lifespan/state](https://asgi.readthedocs.io/en/latest/specs/lifespan.html).
Также прочитаны installed locked uvicorn.Server serve/startup/shutdown иLifespanOn;
собственныйlifecycle выбранчтобынеделегировать повторноеappshutdown библиотеке.
