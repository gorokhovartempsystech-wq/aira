# D03-17C1 — процесс проверки, остановка и подтверждение результата

**Уточнение 3 ноября:** после available E4 подготовлен [проект C1F](d03-17c1f-design.md): dispatcher/PublicationPort, scoped SQL, durable crash fence, bounded supervisor composition. Следующая реализация **Sol6.1 High → F1**, [контракт](d03-17c1f1-contract.md), затем F2/F3 отдельными циклами. Это техническая детализация прежнего F, +2 к оценке: **28–43** самостоятельных цикла. Armed после crash без физического доказательства остаётся quarantine; automatic boot recovery/native production gate не закрыты. Source C1F ещё нет.

1 ноября 2026. Архитектурный цикл на Astra 6 High по прямой команде Никиты; основание — проверенный B3B `7cd3b54` и его [handoff](d03-17b3b-result.md). Это техническое уточнение [D03-17](d03-17-design.md), не новая продуктовая спецификация. F06–F08/F12; F02 затрагивается только границей будущего запуска приложения. [Текущий объём](current-product-scope.md) неизменен.

**Результат этого цикла — проект и контракт C1A, не работающий supervisor.** Разработка C1A–F — отдельными циклами на Sol 6.1 High. B1/B2/B3, V10, старые tests и runner не переписываются. Основная БД остаётся V8. Веса, новый ответ engine `partial/pairwise`, качество модели, frontend, установщик и native Word не входят в C1.

## 1. Решения и границы доверия

Выбран один процесс модели на одну попытку. Backend владеет SQL, арбитром публикации и планировщиком; отдельный небольшой guardian следит за временем/каналом управления и владеет процессом модели. Guardian не импортирует engine, не читает DOCX и не получает DB credentials. Model child получает только immutable B1 request и execution spec через private pipes; он не пишет БД. Real model bridge появится в C2; в C1 запускается явно обозначенный synthetic fixture.

На локальное хранилище/installation identity — один supervisor и один занятый execution slot, в том числе во время cleanup/неопределённого commit. Очередь PostgreSQL из B3 остаётся до 16 queued; параллельные документы не означают параллельную загрузку моделей. Новая попытка не запускается, пока прежний owned child не завершён и прежняя публикация не разрешена. Постоянный warm pool не вводим.

Три независимые истины:

| Область | Кто подтверждает | Чего подтверждение не доказывает |
|---|---|---|
| Child физически завершён | OS handle/wait от живого владельца | Что SQL cancel или success записан |
| Локальное право начать публикацию | Один короткий RAM mutex/арбитр | Что COMMIT принят сервером |
| Итог run/result | SQL fence и проверенное чтение БД | Что зависший OS process уже уничтожен |

Сырые bytes/цитаты/model metadata не попадают в repr, ошибки, traces или stdout приложения. Никаких публичных портов, shell-команд из документа, сети из модели, временных plaintext DOCX/request/reply файлов. Это изоляция доверенного поставляемого кода и защита от сбоев; не security sandbox против вредоносного кода того же OS user. Admitted pack не создаёт subprocess/daemon, не закрывает служебные handles и использует вычислительные threads; эту предпосылку C2 проверяет отдельно. Неизвестный pack не запускается.

## 2. «Стоп» и публикация: точная семантика

Раньше §3 D03-17 говорил «local latch запрещает публикацию», не отделяя уже начатый COMMIT от нового. B3B честно оставил это открытым. RAM и PostgreSQL не имеют общего атомарного действия: после отправки COMMIT разрыв соединения не позволяет определить, записан ли результат. Проверка Event перед вызовом `complete_attempt`, callback после validation или попытка отменить DB query сами по себе гонку не закрывают.

**Уточняем техническое значение принятой остановки.** Запрос Stop немедленно запрещает дальнейшее вычисление и инициирует cleanup. Локальное право запретить публикацию определяется атомарно относительно выдачи commit permit. Если permit уже выдан, Stop остаётся pending до SQL reconciliation; он не обещает отмену ещё не подтверждённого результата. Физический commit может завершиться после нажатия Stop. Это допустимый исход перекрывающихся операций; сообщение «остановлено» до разрешения гонки запрещено. Уже записанный success никогда не удаляется ради отмены. Продуктовые функции/SQL state enum не меняются.

### Арбитр одной попытки

Все переходы ниже под одним коротким mutex, **без SQL, ожидания процесса, парсинга или пользовательских callbacks под mutex**. `stop_requested` монотонен; compute-stop сигнал срабатывает и при `committing/unknown`. `child_closed` означает подтверждённый чистый exit после единственного result frame, EOF и проверки хвоста. Он не выставляется по одному frame.

| Фаза | Событие | Новая фаза / действие |
|---|---|---|
| open | Stop, потеря lease/часов, deadline, storage/child fault | stopped; разрешение на новую публикацию отозвано навсегда |
| open | Результат проверен, SQL gate допустим, child_closed, бюджет жив | committing; один непрозрачный permit, только одному publisher |
| committing | Stop/expiry/fault | committing + stop_requested; cleanup немедленно, итог pending |
| committing | ACK commit | succeeded; подтвердить только записанный/проверенный result |
| committing | Исход COMMIT неизвестен | unknown; ничего повторно не писать до reconciliation |
| committing/unknown | Доказанный rollback/absence под ordered locks | stopped при stop/expiry; иначе open для того же reply, новый permit |
| unknown | Проверенный exact stored success | succeeded, даже если Stop был запрошен в гонке |
| open/stopped/committing/unknown | Подтверждённый другой SQL terminal | terminal; результат не публиковать |
| succeeded/terminal | Поздний Stop/повторный сигнал | Сохранить фактический terminal, не переписывать историю |

Нельзя вернуть `open` после принятого локального Stop, lease loss или истечения времени. Permit привязан к объекту controller и поколению; DTO/UUID из вызывающего кода его не подделывает. После known rollback прежний permit недействителен. Нельзя одновременно иметь два commit attempts. Перезапуск не восстанавливает permits из JSON/PID.

### Добавочный SQL путь C1B

Первоначальный sketch `complete_guarded(...)` уточнён в [C1B](d03-17c1b-result.md) до одного `GuardedPublisher.complete/reconcile` на owned attempt, чтобы сохранять exact permit при unknown commit. Новый путь живёт в `docx_analysis_runs/guarded*.py`. Старый `complete_attempt` и его tests остаются совместимыми, но C1 supervisor никогда его не использует как обход арбитра.

1. Проверить точное совпадение control identity с claim run/attempt/worker/fence; только registered controller живого supervisor, не client DTO. Загрузить **DB** source/request и fully validate B2B вне row locks. Существующий success читать/проверять как replay; он не требует нового разрешения на запись. Подменённый claim buffer не authority. Подготовленный ResultBundle также не принимается от внешнего caller как доказательство.
2. Взять project→document→run→attempt, повторить B3B owner/token/fence/source/request byte identity и fresh DB clock/lease/deadline. Отдельный Session, не общий с heartbeat. Конечный pre-write gate + `control.reserve(now)` — после дорогой validation; каждый ранний отказ выпускает locks.
3. Только с permit записать result+succeeded, flush/deferred constraints, commit одной transaction. Между reserve и commit допускается только этот bounded SQL участок. Нет повторной модели, парсинга или ожидания child. Fresh DB gate — точка принятия решения, а не обещание fsync до deadline.
4. Stop, успевший выиграть mutex, исключает commit; final transaction откатывается. Stop после permit получает pending и параллельно пробует durable `cancel_run`. Row locks определяют SQL победителя. Ошибка/отмена DB-запроса не доказывает rollback COMMIT.
5. ACK потерян: пометить unknown. Новая connection выполняет ordered-lock read, дожидаясь завершения старой transaction. Обычный unlocked SELECT «строки нет» **не доказывает absence**. Если exact success — restore_result и success; если terminal — сохранить его; если still running без result после lock barrier — прежняя публикация не прошла. При Stop сначала durable cancel, без Stop возможен повтор **того же reply** только в живой lease/budget. Wrong digest/corruption — ошибка, без overwrite.
6. Нельзя оживить lease ради восстановления. Если DB недоступна, cleanup продолжается, slot удерживается, UI видит pending/storage unavailable, затем reaper завершает run. Неподтверждённый result не отдаётся как пользовательский success.

New guarded path дублирует минимальный final transaction, переиспользует B2B/B3B read/validation helpers без изменения frozen semantics. Перед реализацией C1B — собственный контракт/acceptance, в том числе forged control/permit, after-flush failure, before/after actual commit, Stop в каждой точке. Новый SQL API не публикуется через HTTP в C1.

### Restart и запрос остановки

Локальный stop intent хранится до разрешения run, а не до ответа HTTP. Отсутствие durable записи при падении backend не разрешает новому процессу допубликовать старый RAM reply: новый supervisor **никогда** не восстанавливает inference/publication для старого running attempt. Он останавливает прежний child через lifetime protocol, ждёт освобождения slot, читает фактический result или даёт lease/reaper завершить interrupted run. Историческое «cancelled» после потери исключительно RAM intent не обещаем; возможен interrupted/timed_out. Данные источника и старые успешные результаты сохранены.

Stop принадлежит scoped backend-команде: unknown/foreign IDs не получают доступа к локальному controller. Владельцем живого controller является accepted runtime scope; при недоступной БД можно остановить только уже привязанный owned attempt. Нельзя выдать новый scope по client IDs. Stop без локального child — обычный durable cancel; off-process caller не имитирует local ACK. Future UI: «Останавливаем…»/«Уточняем результат» до подтверждения; terminal cancelled показывается только вместе с cleanup подтверждением. Durable timed_out/failed при неготовом cleanup не освобождает slot.

## 3. Бюджет времени и планировщик

SQL created+300s и lease≤15s остаются. Для локального времени нужен **continuous monotonic clock, считающий сон компьютера**. macOS — `mach_continuous_time` с целочисленным timebase conversion; Windows — `GetTickCount64` в ns (гранулярность допустима, safety guard 50ms). Обычный wall clock и неподтверждённый portable `time.monotonic` не заменяют этот clock. При resume сначала проверить budget, затем читать frame/публиковать/запускать работу. [Apple continuous time](https://developer.apple.com/documentation/kernel/1646199-mach_continuous_time), [Microsoft Windows time](https://learn.microsoft.com/en-us/windows/win32/sysinfo/windows-time).

Перед claim запомнить continuous `s`, после ACK — `r`. Local `D = s + (DB deadline - claimed_at)`, `L = min(D, s + (lease_expires_at - claimed_at))`; преобразование точное, без float. Это консервативная оценка: latency подготовки/commit не добавляет времени. При `r >= min(D,L)-guard` child не стартует. Для accepted heartbeat взять `s_h` до вызова и `L_candidate = s_h + (new lease - new heartbeat_at)`, clamp к D; ACK должен прийти **до прежнего** локального L. Поздний ACK не оживляет попытку даже если SQL продлил lease. D никогда не увеличивается. Неверный clock/переход назад останавливает попытку, не корректирует время вверх.

Guardian получает absolute D/L той же host clock domain, sequence и fixed attempt identity. Deadline/lease передаются как canonical decimal strings, чтобы JSON transport не терял ns precision; D неизменен, L≤D и не дальше15s от момента отправки. Пульс не означает успешный SQL heartbeat: разрешённый L меняется только после accepted heartbeat; stale/duplicate pulse не продлевает срок. Отдельный watchdog не зависит от GIL модели/codec. Supervisor control loop стремится к tick≤250ms, heartbeat запускается каждые3s (не позже5s в норме), reaper раз в1s, один heartbeat in flight. После первой storage-ошибки вычисление останавливается; новый lease не запрашивается ради продолжения после сбоя. Missing pulse/старый L останавливает child даже при зависании всего backend.

Во время B2B validation heartbeat и Stop обслуживаются отдельным control dispatcher, с отдельными DB connections в bounded I/O jobs; тяжёлая работа не выполняется под его mutex. Dispatcher не ждёт SQL: получает completion messages и выдаёт publisher разрешение коротким синхронным обменом. Все `now_ns` измеряются им непосредственно перед pure переходом, ACK received time включает задержку доставки dispatcher. Так перестановка двух заранее измеренных timestamps не выглядит как rollback часов. При перегруженной bounded очереди Stop хранится отдельным coalescing флагом и обрабатывается раньше нового reserve; неподтверждённый reserve при timeout caller не отправляет COMMIT, затем reconciles state. Планирование Python не real-time: при голодании GIL guardian прекращает попытку по последнему разрешённому L, вместо обещания бесконечно поддерживать heartbeat. Приёмка включает такую остановку и обычный CPU-heavy happy path.

Для supervisor-owned DB engine: небольшой bounded pool, отдельный control connection reserve; connect timeout2s, lock timeout500ms, statement timeout2s, idle-in-transaction timeout2s, общий local budget финализации5s. Это настройки **отдельного** runtime, не переписывание глобального engine. Проверить доступные PG/libpq версии при C1F, не объявлять network/fsync timeout абсолютной OS гарантией. Зависший DB job не вызывает бесконечное создание новых threads/connections: максимум один незавершённый publisher, один control job и один reconciliation job; slot остаётся blocked. Успех cancel query не равен доказанному исходу COMMIT. [PostgreSQL timeout semantics](https://www.postgresql.org/docs/18/runtime-config-client.html), [Psycopg concurrent operations](https://www.psycopg.org/psycopg3/docs/advanced/async.html).

Scheduler запускается только явным `start()` desktop/backend bootstrap и имеет явный `shutdown()`. Он работает без открытого UI, вызывает B3 reaper и claim при свободном slot; у shutdown нет неявного нового claim. Queue status проверяется до каждого spawn. Unknown claim ACK не вызывает повторный inference: прочитать durable state, не переиспользовать случайный чужой token; если claim невозможно надёжно восстановить — ждать reaper. Для queued runs текущего процесса хранить conservative D; при runtime restart не продлевать уже принятые queued jobs: startup reconciliation завершает старые queued как interrupted через новый узкий service C1F, после scope/ordered locks. После получения единоличного runtime ownership, **под прежним enqueue advisory lock**, скопировать bounded набор queued IDs, затем отпустить advisory lock и обработать эти IDs в обычном project→document→run порядке с recheck queued. Новые IDs не входят в этот набор; wall-clock cutoff/переименование deadline не используются. Admission после startup barrier — только через этот supervisor. Незарегистрированный внешний writer остаётся вне поддержанного desktop runtime, не получает новый monotonic budget из чтения строки. SQL clock alone не даёт защиты queued jobs от sleep/clock rollback; этот путь обязателен, отдельные tests до кода.

Для fresh enqueue C1F фиксирует continuous start **до** B3A start_saved/retry и регистрирует `D<=start+300s` по принятому run ID до возврата пользовательского ACK. Exact replay не переякоряет D; startup набор старых queued IDs уже обрабатывается отдельно. Потеря enqueue ACK восстанавливается по durable key без нового model budget. Нельзя вычислять «ещё300s» от момента очередного poll.

Cold model loading входит в300s. F02 preload/model startup при открытии приложения остаётся отдельным desktop контрактом: C1 не закрывает F02. Нет выдуманных процентов: preparing_document — supervisor, loading_model/analyzing — реальные bridge события, validating_result/finishing — backend. Не выводить стадии «лексика/логика», пока C2 не поддержит точные сигналы.

## 4. Закрытый протокол `aira-worker/1`

Три независимых направления: parent→child request; child→parent events; supervisor→guardian control. Большой request или stderr не блокирует Stop. EOF control трактуется как остановка; writer handle принадлежит только supervisor и не наследуется моделью/guardian. Guardian→supervisor status — отдельный bounded канал без текста документа. Numeric FD/handle в trusted argv допустим; input bytes/DB URLs/секреты/произвольный document path — нет.

Каждый frame: 4 bytes unsigned big-endian length, затем ровно N bytes UTF-8 JSON object. Лимиты frame в таблице относятся к N, prefix учитывается дополнительно по4bytes/frame; MiB=2**20, KiB=2**10. Zero/oversize отклоняется до выделения body. Duplicate keys, NaN/Infinity, bool вместо int, invalid UTF-8/surrogate, depth>4, extra fields, version/identity mismatch запрещены. Canonical output: sorted keys, compact separators, no ASCII escaping. Envelope строго содержит `protocol`, `kind`, `run_id`, `attempt_id`, `seq`; UUID canonical lowercase, seq exact nonnegative int≤1024. Последовательность отдельная по направлению, с0, gaps/replays запрещены. Body данные не интерпретируются как Python/pickle/module names.

| Frame | Дополнительные поля | Ограничение |
|---|---|---|
| parent `run` | worker_instance_id, claim_fence=1, request_sha256, execution_spec_sha256, request_b64, execution_spec_b64 | Один frame≤12MiB; decoded request≤8MiB, spec≤4KiB |
| child `ready` | execution_spec_sha256 | Один, после admission/перед loading; ≤4KiB |
| child `stage` | stage=loading_model или analyzing | По одному в этом порядке; ≤4KiB |
| child `result` | reply_sha256, reply_b64 | Один terminal frame≤6MiB; decoded reply≤4MiB |
| child `error` | code из model_unavailable/model_input_limit_exceeded/adapter_error/analysis_limit_exceeded | Один terminal frame≤4KiB; свободного message/trace нет |
| control `permit` | deadline_ns, lease_ns | ≤4KiB; не более512 frames/1MiB за lifetime |
| control `stop` | reason=user/deadline/lease/storage/shutdown/protocol | Один, ≤4KiB; закрытие pipe также Stop |
| guardian `closed` | exit_kind=clean/stopped/crashed, exit_code bounded signed32, cleanup_confirmed bool | Один terminal status≤4KiB |

Base64 строго RFC4648 standard с padding, без whitespace, проверять decoded cap **до** decode и каноническую повторную кодировку; hashes lowercase SHA256 exact bytes. Base64 сохраняет исходный B1 reply, без повторной JSON сериализации. Не новый ML schema: B1/B2 валидируют decoded payload отдельно. Ready/spec digest не доказывает подлинность произвольного executable — pack admission отдельный.

Child event stream: ready→loading_model→analyzing→result→EOF→exit0; error разрешён вместо любого ещё не отправленного terminal, включая отказ до ready. Не более4 frames на success, суммарно≤6MiB+12KiB; лишний stdout byte/frame, result+error, второе result, trailing partial header, unexpected stage — adapter_error. Error exit ненулевой; result с ненулевым exit не success. До EOF+подтверждённого exit result — только private candidate. Запрещён `communicate()` с неограниченным накоплением output. Incremental decoder хранит не больше одного bounded frame; чтение chunks≤64KiB. Stderr постоянно drain/discard, максимум64KiB lifetime, превышение прекращает child; bytes не возвращаются в ошибке. Flood/truncated/slow frame подчиняются общему D/L, не получают отдельные300s.

Не наследовать полный environment. Explicit launch config строит минимальные OS значения: Windows SystemRoot/WINDIR из проверенного OS location, sandbox-local TEMP/TMP при необходимости; фиксированные locale/encoding/thread-count flags. Никаких PG*/DATABASE_URL/API keys/proxy/PYTHONPATH/PYTHONHOME/DYLD*/LD_PRELOAD. Использовать абсолютный installer-resolved executable и фиксированный module/bridge entry; Python isolated mode, shell=False, trusted cwd, handles allowlist. Тестовый executable/fixture path доступен только injected test driver, не через пользовательский API. [Python 3.12 subprocess handles/start_new_session](https://docs.python.org/3.12/library/subprocess.html).

Ограничения buffers — не обещание RSS всей модели. В C1 ограничены количество процессов/jobs, очереди событий, вход/выход и время; копии source/request/reply учитываются в измерении пиков backend. Полный payload не дублировать в diagnostic queues, event callback хранит locator/counter. Значения RAM/model thread budget для real pack задаёт C2 после benchmark; неподтверждённые «любой компьютер» или production memory caps не вводить. Fixture flood tests подтверждают bounds протокола, а не ресурсные требования ONNX.

## 5. Владелец процесса и slot

Два разных lock files в canonical private app-data directory, по одному на локальное хранилище, не на run: **runtime.owner** удерживается только supervisor всю его жизнь; **analysis.slot** резервируется до claim и разделяется с guardian/model до cleanup+SQL reconciliation. Порядок owner→slot, никогда обратный. Второй runtime получает runtime_busy. После падения первого новый может получить owner, но живой orphan всё ещё удерживает slot и запрещает новый claim/spawn. Не unlink/replace locked inode, не создавать путь из document name, не удалять «stale lock» по PID. Проверить owner/type/permissions и symlink/reparse traversal.

Lifetime slot handle разделён с child, поэтому падение parent не освобождает slot раньше child. Runtime может закрыть свой reference, но не делать явный unlock общего lock, пока child жив. После cleanup и разрешения SQL закрыть slot references и проверить slot через новое независимое open/lock, продолжая держать runtime.owner; это защита от живого orphan, не способ найти и убить его. Нельзя подтверждать cleanup по освобождению лишь runtime.owner. Закрытие приложения освобождает owner после Stop/cleanup либо оставляет наследуемый slot закрывать повторный запуск при незавершённом cleanup.

### macOS

Минимальный guardian — отдельный доверенный процесс, прямой родитель model child; именно он создаёт новую session/process group child и хранит прямое child ownership. Он не выполняет SQL/ZIP/ML. Model стартует за private handshake barrier: никакого engine import/inference до готовности control/watchdog/slot и команды run. Creation/exec использует штатный безопасный spawn путь, не `preexec_fn` в многопоточном backend.

Guardian удерживает leader unreaped до последнего возможного сигнала группе: `kqueue EVFILT_PROC/NOTE_EXIT` для уведомления без reap; при необходимости TERM/grace≤2s/KILL, затем waitpid конкретного child. **Уточнение [C1D](d03-17c1d-design.md):** observed NOTE_EXIT сначала навсегда закрывает право сигналить, затем позволяет wait без сигнала уже завершившемуся процессу. EPERM/ESRCH не доказывает cleanup: запретить дальнейшие сигналы, ждать независимый exact wait; без него pending/busy. Не звать `Popen.poll()/wait()/send_signal()` до закрытия права group signal. В текущем Python3.12 macOS `os.waitid` отсутствует, поэтому проект на него не опирается. При неизвестном ownership запретить kill и новый spawn. [Apple kqueue](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kqueue.2.html), [waitpid](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/wait.2.html), [killpg](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/killpg.2.html).

Точный startup barrier/FD ownership — [C1D](d03-17c1d-design.md): отдельные prepared/gate/armed private tokens, engine не импортируется до GO+valid run. Frozen C1C wire не расширяется bootstrap ACK. Реализация разделена на D1 primitives, D2 guardian/bootstrap, D3 parent transport/native matrix; первый [контракт D1](d03-17c1d1-contract.md) готов.

Slot — `flock(LOCK_EX|LOCK_NB)` на одном open file description, передан через explicit pass_fds guardian и model, закрывается без `LOCK_UN`. [Apple flock inheritance](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/flock.2.html). На EOF control/сроке guardian останавливает group независимо от GIL модели. Parent death во время большого request/ML/validation также закрывает единственный writer control.

Ограничение честное: process group не эквивалент Windows Job и не доказывает уничтожение произвольного daemon, ушедшего в другую session. Поэтому C1/C2 допускают только threads-only model child; spawn descendants не входит в допустимый pack. Одновременная гибель backend/guardian или SIGKILL guardian при живой зависшей модели может оставить orphan. Slot reference модели тогда запрещает новый запуск; новый backend **не** убивает по старому PID, сообщает runtime_busy и не выдаёт cleanup confirmed. Сам bridge следит за guardian EOF как дополнительная защита, но его Python thread не считается гарантией при GIL/native hang. Автоматическое восстановление после такого двойного отказа не заявляется; отдельный OS broker потребовал бы нового контракта. Это уже допустимая fail-closed ветка D03-17, не silent overlap.

### Windows

**Уточнение 2 ноября 2026:** нормативный Windows lifecycle задан [C1E](d03-17c1e-design.md) и [контрактом E3](d03-17c1e3-contract.md). E1/E2/[E3 available implementation](d03-17c1e3-result.md) проверены, native Windows gate pending. Исторический эскиз ниже **не инструкция для реализации**: create→Assign/передача запасного process HANDLE заменены JOB_LIST и двумя вложенными Job. Неизвестный pre-return исход не даёт cleanup ACK; автоматическое restart recovery требует отдельного durable fence/gate в C1F. Следующий шаг — [exact E4 design](d03-17c1e4-preflight.md) на Astra6 High, затем Sol implementation.

Guardian владеет anonymous Job Object с `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, без breakaway, limit active processes1 для threads-only bridge. Только guardian имеет Job handle; он **не наследуется моделью**. Launch: CreateProcessW CREATE_SUSPENDED с explicit inherited handle list, AssignProcessToJobObject, затем ResumeThread. При ошибке assignment убить suspended owned process через retained HANDLE, дождаться exit, не resume/fallback. Неподдерживаемая nested Job конфигурация — runtime unavailable. [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject), [handle list](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute).

Startup interval до Job assignment: child suspended и engine не запущен. Guardian failure здесь не должен оставлять suspended process/slot навсегда незамеченным: C1E имеет отдельный crash cut-point и cleanup handoff с retained process HANDLE у supervisor до assignment ACK; после смерти обоих процессов безопасность остаётся busy, не успех. Предпочтительный production hardening — atomic job assignment при creation, если поддерживается выбранным Windows API; он требует отдельного проверенного binding, не предполагается готовым в Python Popen.

Stop через control, grace≤2s, затем TerminateJobObject; ждать process handle signalled и job active count0. Job notifications — wakeup, не единственное доказательство cleanup. Не использовать taskkill/имя процесса/сохранённый PID. Slot — file HANDLE с deny sharing, explicit duplicate у guardian/model; unnamed mutex с abandoned state один не подходит (владелец уже умер, child ещё может жить). Все handles закрываются ровно один раз. Native Windows acceptance обязательна; mock ctypes на Mac её не заменяет.

## 6. Матрица обязательной приёмки

| Группа | Минимальные случаи и ожидаемый результат |
|---|---|
| Арбитр | Stop до/после reserve; два publishers; deadline equality; lease ACK late; rollback/unknown; forged/stale permit; committed после Stop; irreversible latch; bounded mutex без callbacks |
| SQL | Stop во время B2B validation, до reserve, после flush/на commit; ACK loss до/после реального commit; locked absence vs незавершённая transaction; scope transfer/deletion; previous result intact |
| IPC | Header/body по1byte, coalesced frames, max/+1 caps, duplicate keys/seq, invalid UTF8/base64/digests, wrong attempt, extra/trailing bytes, stdout/stderr flood, child closing request, result then hang/crash |
| OS | Stop while loading/inference/write; ignored TERM; parent/guardian death; creation barrier; leaked control writer; stale PID без kill; slot release after actual exit;2 concurrent supervisors; second spawn before cleanup denied |
| Time | DB wall forward/backward; suspend/resume >deadline; clock rollback/overflow; heartbeat slow/late; validator GIL starvation; DB stalled beyond lease; guardian observes last permit only |
| Recovery | Unknown claim/complete/cancel; no fresh inference for running; queued-before-restart interrupted; terminal SQL + live child keeps busy; no UI reaper; shutdown stops admission; no unbounded retry workers |
| Integrity | Source/request bytes pinned, invalid/partial reply не no_findings; fixture remains fixture; no secrets/env/doc diagnostics; inert imports, bounded buffers; no production schema/data changes |

Tests используют synthetic child/documents и disposable PG. Никаких actual model/секретов/работы пользователя/desktop dialogs. Native-only tests маркируются честно; platform skip не закрывает release gate. Блокировка Windows среды не препятствует pure/SQL/macOS циклам, но не превращается в «Windows проверена».

## 7. Последовательность реализации

| ID | Одна ответственность | Allowed boundary / выход |
|---|---|---|
| **D03-17C1A** | Pure budget и Stop/publication arbiter | [Выполнен](d03-17c1a-result.md), gate3025+24; без процессов/SQL |
| C1B | Guarded SQL completion/reconciliation | [Выполнен](d03-17c1b-result.md), gate3057+24; old B3B untouched |
| C1C | Strict bounded wire codec | [Выполнен](d03-17c1c-result.md), gate3121+24; без модели/SQL/OS launch |
| C1D | macOS guardian/slot/continuous clock | D1/D2/[D3 выполнены](d03-17c1d3-result.md), итог gate3247+24; synthetic Mac supervision/transport, без real engine/SQL supervisor |
| C1E | Windows ownership/slot/clock | E1–E4 available implementation; [E4 итог](d03-17c1e4-result.md):3508passed+24subtests/41native skipped,exit0. Подготовка теста исправлена. Native gate отдельно, весь Windows runtime ещё не принят |
| C1F | Explicit supervisor/scheduler + lifecycle wiring | [Design готов](d03-17c1f-design.md); Sol6.1 High → F1 dispatcher, F2 SQL/ledger, F3 composition. [Контракт F1](d03-17c1f1-contract.md); перед каждым следующим source свой freeze. Boot recovery/native release gate открыты |

Каждый цикл: контракт→acceptance freeze→red→реализация→targeted/full gate→result/local commit. C1B–F должны до кода зафиксировать exact API/allowed paths/tests, не использовать эту таблицу как разрешение править весь backend. Автоматический переход разрешён пользователем, если контракт однозначен и текущего режима достаточно. Windows environment gate можно отложить с явным ограничением, продолжая независимую работу. Никаких push/публикации в этом проектировании.

После C1A/B/C завершены D1/D2/[D3](d03-17c1d3-result.md), gate3247+24. Дополнение Stop реализовано, old frozen tests/C1A/B/wire unchanged. **C1E Windows спроектирован 2 ноября на Astra6 High**: [design](d03-17c1e-design.md), [результат](d03-17c1e-result.md). Следующий шаг **Sol6.1 High, D03-17C1E1**, затем E2/E3/E4 отдельными циклами. Atomic Job creation, nested ownership и overlapped cancellation lifetime определены; Mac mocks не закрывают native Windows gate. Актуальный самостоятельный остаток **30–45**: прежние27–42 после D3 плюс3 за уточнение одной Windows-строки до четырёх реализаций, без новых продуктовых функций.

Историческая оценка после первоначального C1 design была31–46 (одна строка C1→шесть). После реализованных A/B/C она стала28–43; уточнение C1D одной строки→три даёт актуальные **30–45 самостоятельных implementation/design циклов**. Новых продуктовых функций нет. Завершённое проектирование повторно в остаток не включено; диапазон не потолок. Native Windows/Word, настоящий frontend/weights и совместный релиз — внешние gates, не выдуманные завершённые циклы.
