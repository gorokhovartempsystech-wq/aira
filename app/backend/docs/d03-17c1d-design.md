# D03-17C1D — macOS: запуск, владение процессом и подтверждение остановки

1 ноября 2026, Astra 6 High. Проектирование по прямой команде Никиты после C1A–C1C (`0f9b335`); [handoff](d03-17c1c-result.md). Это детализация §5 [C1](d03-17c1-design.md), F06–F08/F12. [Продуктовый объём](current-product-scope.md), C1A/guarded SQL/C1C wire, V10 и старые tests не меняются. Реализации D в этом цикле нет.

**Выход:** три последовательных implementation цикла D1–D3, первый с [точным контрактом](d03-17c1d1-contract.md). Sol 6.1 High достаточно для их реализации. Настоящий engine/weights/admission остаётся C2; Windows — C1E; SQL scheduler/recovery — C1F. C1D использует явно synthetic child, не выдаёт его за ML. Проверки и handoff design-cycle — [в результате](d03-17c1d-result.md).

## 1. Что уточнено относительно общего C1

1. Не отправляем сигнал уже подтверждённо завершившемуся leader. `NOTE_EXIT` переводит владельца в необратимое состояние «сигналов больше не будет»; затем выполняется wait конкретного child. Допущенный pack использует только threads. Наличие произвольных descendants не пытаемся доказать process group API.
2. `EPERM`/`ESRCH` не означает ни успех остановки, ни доказательство живого процесса. После ошибки прекращаем сигналы, получаем независимое exit/wait evidence; без него остаётся cleanup pending. [Уточнение D2](d03-17c1d2-stop-addendum.md): отдельный sticky signal_error не равен hard_fault; ordinary Stop с exact wait без hard fault может дать stopped при сохранённом общем fault. Нет повторной попытки через иной kill API/утилиту, старый PID или повышение прав.
3. Готовность guardian — отдельный маленький bootstrap protocol `aira-native-bootstrap/1` на private pipes. **Ни одного нового kind/field в frozen `aira-worker/1`.** `ready` C1C — событие model bridge после admission, не разрешение запуска watchdog.
4. У supervisor раздельны control writer и data pump: большой request/reply не занимает lock Stop. Guardian вообще не читает request/reply и не импортирует SQL/DOCX/engine.
5. Физический exit, корректный result stream, SQL terminal и освобождение slot проверяются отдельно. Ни `closed`, ни свободный owner lock, ни errno не заменяют остальные проверки.

## 2. Процессы, доверие и передача дескрипторов

Обозначения: S — supervisor/backend, G — guardian, M — minimal model bootstrap с synthetic adapter в C1D. G — прямой родитель M, S — прямой родитель G. На attempt один G и один M; ни restart M, ни pool. Оба Popen objects удерживаются владельцами до завершения. G единолично выполняет все действия над M в одном event loop; SIGCHLD устанавливает в SIG_DFL до spawn, не использует общий reaper или `waitpid(-1,...)`.

Разрешён обычный `subprocess.Popen`, `shell=False`, `close_fds=True`, `start_new_session=True`, exact `pass_fds`, без `preexec_fn`. В частности, G и M находятся в разных sessions/groups, группа M имеет PGID=PID M. Нет зависимости от экспортируемой Python константы POSIX_SPAWN_SETSID. Popen — retained creation evidence, PID не сохраняется на диск и не принимается из запроса. Нельзя вызывать Popen.poll/wait/send_signal/terminate/kill для M, пока ещё возможен group signal. G использует `os.killpg` непосредственно; после конечного wait устанавливает сохранённый returncode, чтобы последующая очистка Python не пыталась reap повторно. S может poll/wait своего G: S никогда не сигналит группу M.

Документация Python описывает управление наследованием FD, environment и создание session; также предупреждает, что системная фаза создания процесса не всегда прерываема. Поэтому C1F выполняет spawn отдельным bounded job (не более одного), не в control dispatcher. Зависший spawn не оправдывает второй spawn или бесконечное создание threads. [Python subprocess](https://docs.python.org/3.12/library/subprocess.html).

| Resource | S после передачи | G после передачи M | M | Правило |
|---|---|---|---|---|
| runtime.owner | единственный FD | нет | нет | Нельзя наследовать |
| analysis.slot | свой reference | reference того же open description | reference того же description | Только close; никогда LOCK_UN |
| control S→G | единственный writer | reader | нет | Потеря S даёт EOF независимо от data pump |
| status G→S | reader | единственный writer | нет | Один C1C closed, затем EOF |
| request S→M | единственный writer | только временный reader до spawn | reader | G закрывает свою копию сразу после spawn |
| events M→S | reader | только временный writer до spawn | единственный writer | G закрывает свою копию сразу после spawn |
| stderr M→G | нет | reader | writer fd2 | G drain/discard, счётчик ≤64KiB |
| bootstrap armed G→S | reader | единственный writer | нет | Один token A и EOF |
| bootstrap prepared M→G | нет | reader | единственный writer | Один token P и EOF |
| bootstrap gate G→M | нет | единственный writer | reader | Один token G, writer жив до остановки/exit |

G stdin/stdout/stderr — DEVNULL. M stdin/stdout можно назначить request/events; stderr только отдельный pipe. Ни пользовательский терминал, ни DB/socket FD не наследуются. Неиспользуемые концы всех pipes закрываются сразу в каждом процессе, также на каждом exception cut point. FD по умолчанию non-inheritable; временная передача только exact pass_fds штатного spawn. Владельцы reader не держат случайную копию writer. У M нет control/status/armed/owner FD и gate writer. У G нет supervisor control writer. EOF определяется реальным `read()==b''`, не только флагом kqueue EV_EOF: перед EOF ещё могут быть bytes. [Apple kqueue](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kqueue.2.html).

Launch plan задаёт только trusted installed executable/entry/cwd. В C1D разрешена явно названная synthetic factory; нет product endpoint для executable/path/argv/env. C2 добавит factory допущенного pack. Python запускается `-I -B`, фиксированный entry, абсолютный executable, trusted cwd; import пути не берутся из документа или environment. Установленный package либо фиксированный bootstrap root задаётся packaging, не PYTHONPATH. Minimal env создаётся с нуля (фиксированные locale/encoding/thread flags); не копировать os.environ. HOME, PG*, DATABASE_URL, API keys, proxy, PYTHON*/DYLD*/LD_* не передаются. Нужда реального pack в cache/temp — отдельное C2/desktop решение. В argv разрешены только fixed entry, FD numbers, attempt UUIDs и initial D/L; документ, request/spec, секреты, текст ошибок туда не попадают.

M не порождает subprocess, не setsid/setpgid повторно, не закрывает slot, не открывает сеть. Это требование к допущенному поставляемому коду, **не security sandbox** против произвольного кода того же OS user. C1D не заявляет доказанную пригодность неизвестного engine.

## 3. Bootstrap `aira-native-bootstrap/1`

Это имя внутреннего протокола, не JSON envelope. Три однонаправленных private pipe; каждому запуску создаются новые FD. Полная payload каждого сигнала — ровно 8 bytes:

| Канал | Bytes literal | Семантика |
|---|---|---|
| M→G prepared | `b'AIRA-N1P'` | Minimal launcher и наблюдение gate подготовлены; engine ещё не импортирован |
| G→M gate | `b'AIRA-N1G'` | G зарегистрировал ownership/watchdog и разрешает прочитать run |
| G→S armed | `b'AIRA-N1A'` | G выполнил launch barrier; S может передавать request |

Prepared/armed требуют ровно token + EOF; prefix, wrong byte, extra byte, отсутствие EOF — не успешный ACK. Gate требует ровно token; после него writer остаётся открытым, любой следующий byte или EOF прекращает M. Не нужен client nonce: связность определяется fresh private pipe topology и фиксированными identity в trusted launch args/C1C frames; token не переносимая capability и не доказательство личности чужого executable. Копия bytes/отправка в произвольный pipe не выдаёт никакого публичного права запуска.

Порядок:

1. S уже держит runtime.owner и slot **до claim**. После accepted claim C1A даёт initial guarded D/L. S подготавливает маленький permit seq0 и private FD, запускает G; начальные D/L также переданы G для deadline ещё до чтения permit. G не создаёт M до полного permit seq0 с теми же D/L. Никакого автоматического расширения срока при bootstrap.
2. G открывает continuous clock/kqueue, регистрирует control/status plumbing, проверяет initial `now < L <= D`, `D-now<=300s`, `L-now<=15s`, наличие slot. Управление control имеет высший приоритет. G создаёт gate/prepared/stderr и M через безопасный spawn.
3. M начинает только stdlib/bootstrap/wire code, проверяет inherited descriptors/identity и initial clock. До gate действует initial D/L, poll≤100ms; ожидание разрешения не бесконечное. Никакого engine import или чтения request до gate. M подготавливает отдельный reader gate: до token он разрешает старт через Event, после token следит за EOF/extra byte и завершает процесс фиксированным safe exit без traceback. Prepared отправляется лишь после запуска этого reader; подготовка сама по себе не разрешает main thread выполнять adapter.
4. G регистрирует `EVFILT_PROC | NOTE_EXIT` M, получает полный prepared+EOF, повторно обслуживает control/Stop/clock. Если child уже вышел, регистрация неуспешна, Stop/EOF/error/expiry — gate не отправляется. Иначе G посылает gate, затем armed и закрывает armed writer. Обе записи nonblocking и короткие; failure ведёт в teardown, не в повторный spawn.
5. S принимает полный armed+EOF, снова проверяет свой Stop и live budget, только потом пишет run и закрывает request writer. M принимает один корректный C1C run+EOF, сверяет binding/spec и выполняет admission synthetic adapter. Только теперь ready→loading_model→analyzing. Будущий engine import допускается после этой точки и проверки gate-lost flag. Guardian может остановить M между любыми двумя инструкциями; атомарность запуска engine относительно будущего Stop не обещается.

Minimal gate reader M после GO больше не использует initial L: его уже мог продлить G. Весь текущий D/L дальше проверяет независимый G. M reader — дополнительная защита от смерти G; при удержании GIL/native hang он может не исполниться, поэтому не является гарантией cleanup. G закрывает gate на Stop до сигналов. Buffered gate token + немедленный EOF не превращается в разрешение продолжать inference.

S death до/во время request закрывает control: G начинает teardown. G death до GO даёт EOF gate; inference не начинается. Если G погиб в самой spawn/exec фазе, slot M и gate/initial-budget bootstrap предотвращают параллельный запуск; прерываемость всех kernel spawn фаз не обещаем. После GO двойной отказ G/S может оставить живой M; slot удерживает busy (§8).

## 4. Continuous clock и правила разрешения времени

Все три процесса используют один clock domain: `mach_continuous_time`, `mach_timebase_info`, integer `ticks*numer//denom`. `ctypes` signatures явно uint64/uint32 и kern_return_t, загрузка только при explicit now, не при import. denom/numer положительны; native error/отсутствие symbol/overflow за signed63/backwards reading — clock_unavailable, без fallback на wall time/обычный monotonic. Равные readings допустимы. Apple определяет continuous clock как продолжающий идти во время сна; timebase — рациональное преобразование ticks. [Apple mach_time.h](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/osfmk/mach/mach_time.h).

D/L уже содержат guard C1A, **второй guard в G не вычитается**. Перед обработкой buffered controls проверяется старый L; `now >= L` останавливает, даже если поздний permit продлевает его. D фиксирован первым permit, L может сокращаться/продлеваться только в пределах D и `now+15s`. Seq/order/caps C1C обязательны. Новая дата из argv, pulse без accepted SQL heartbeat, queued permit после старого L не продлевают жизнь.

G делает wait не дольше min(100ms, ближайший L/D/grace), проверяет время **перед каждым** gate/readiness/signal решением и сразу после wake/resume. Сначала Stop/EOF/expiry, затем разрешающие сообщения. Большой stderr не монополизирует loop: ≤64KiB за drain-turn, после него снова control/time; lifetime>64KiB — fault. G не делает B1 JSON parsing, модель или SQL. Тайм-аут не перезапускает attempt.

TERM grace максимум2s continuous от первого Stop; повторные Stop не сдвигают срок. После сна дольше grace — сразу final KILL при сохранившемся owned live child, без новых2s. При поломке clock безопасно вычислить grace нельзя: сразу final KILL. Это политика планирования на работающей ОС, не hard real-time гарантия при starvation/kernel hang. Локальный timeout/status не доказывает физический exit.

## 5. Единственный владелец M: сигналы, NOTE_EXIT, wait

У G есть private ownership record: retained Popen, PID от успешного spawn, fixed PGID=PID, `signals_open`, `exit_seen`, `wait_status`, Stop/fault latch. Запись не сериализуется и не конструируется из DTO/файла. Все переходы ниже выполняет один loop; нет отдельно поставленных в очередь callbacks с raw PID. Object нельзя copy/deepcopy/pickle.

| Состояние/событие | Действие |
|---|---|
| spawn успешно, child не reap | `signals_open=True`; PID pinned прямым unreaped child |
| NOTE_EXIT для exact PID/filter без EV_ERROR | `exit_seen=True`; сначала `signals_open=False`, затем wait exact PID; никаких group signals после этого |
| Stop/EOF/expiry/protocol fault при ещё возможном live child | Закрыть gate, latch Stop; проверить pending NOTE_EXIT; если нет — один SIGTERM группе, grace≤2s |
| Grace истёк, exit ещё не наблюдался | Последняя проверка NOTE_EXIT; один SIGKILL группе, затем безусловно `signals_open=False` |
| Native clock/kqueue/bootstrap fault, безопасное ожидание невозможно | Не выдавать GO; если ownership известен, один final SIGKILL до закрытия signals; дальше только wait |
| killpg вернул ошибку (включая EPERM/ESRCH/EINTR) | Закрыть signals навсегда, перейти к wait WNOHANG; sticky signal_error/fault сохраняется и после wait. Не повторять signal. Отдельная классификация hard fault и итогового kind — [D2 дополнение](d03-17c1d2-stop-addendum.md) |
| waitpid(exact PID,WNOHANG) вернул0 | Ещё нет exit proof, cleanup pending; bounded poll, никаких новых сигналов |
| waitpid вернул exact PID и exited/signalled status | Reaped, сохранить exit code (`-signal` для signal); закрыть G slot reference и только теперь сформировать closed |
| wait ECHILD/неожиданный PID/не-terminal status | Ownership fault, cleanup не подтверждён. Не угадывать exit code, не kill по PID, не новый spawn |

Wait разрешён **только после необратимого закрытия signals**. Ранний NOTE_EXIT на natural exit позволяет не слать бессмысленный final kill; после получения exit мы не обязуемся добивать неизвестные descendants. Проверка group existence (`killpg(...,0)`) не используется как доказательство владения или остановки. Если NOTE_EXIT registration не удалась, GO запрещён; retained direct child ещё позволяет ровно один final signal, затем только WNOHANG wait. Сломанный wait/kqueue не подменяется `ps`/`pgrep`/поиском имени процесса.

`waitpid` с положительным PID относится к конкретному child, WNOHANG позволяет не блокировать event loop; ошибки не превращаются в выдуманный returncode. [Apple wait](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/wait.2.html). Документированный EPERM killpg связан с правами, ESRCH — с отсутствием группы. [Apple killpg](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/killpg.2.html). В исходнике XNU группа без подходящих незомби-процессов также может приводить к EPERM; это объясняет возможную гонку, но не устанавливает причину любого EPERM на текущей ОС. Вывод о cleanup строится по wait evidence. [Apple XNU killpg1](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_sig.c#L1612-L1624).

Успешная отправка SIGKILL тоже не exit proof. После final signal G сохраняет record и slot, ждёт actual wait; при неубиваемом kernel wait может оставаться pending. На ошибке сигнала естественный последующий exit может подтвердить cleanup; разрешения продолжить вычисление/выдать clean result уже нет. Исключение — если независимо наблюдён natural exit **до** какого-либо Stop/fault, сигнала вообще не было и обычный clean путь допустим.

## 6. Каналы, статус и candidate

G отправляет `closed` только после exact wait M, с реальным exit_code. `cleanup_confirmed=True` означает direct threads-only child reaped; это не доказательство SQL success или отсутствия произвольного daemon. По [уточнению D2](d03-17c1d2-stop-addendum.md) kind выбирается последовательно: hard_fault→crashed; ordinary Stop→stopped; signal_error без Stop→crashed; иначе exit0→clean, ненулевой→crashed. Общий child.fault не очищается и не заменяет отдельный hard_fault. Если нет child/wait evidence или lost ownership, G не сочиняет `closed(exit_code=0)`: закрывает status без frame при окончательной ошибке либо остаётся pending. Driver знает, что EOF без valid closed — потеря подтверждения. C1C closed с `cleanup_confirmed=False` не принимается как разрешение публикации.

G закрывает свой slot после wait, отправляет bounded status, закрывает status и выходит0 после штатной передачи любого kind closed. Startup/native failure без подтверждения даёт ненулевой exit G; это не exit_code M. Status write не блокирует teardown: частичные writes/nonblocking, до2s continuous после wait, при EPIPE прекратить немедленно. При неисправных часах допускается лишь один nonblocking write, затем закрыть канал; ждать новый timeout по сломанному clock нельзя. При отсутствии подтверждения S будет консервативен. M stderr никогда не возвращается/logged: >64KiB — crashed/fault и teardown, включая flood после result. G не знает содержимое result, поэтому clean status — лишь OS часть доказательства.

S data pump имеет один thread на attempt; обслуживает request/events/status/armed и G stderr только если тестовый transport его явно захватывает. Production G stderr DEVNULL. Все data pipes nonblocking, chunks≤64KiB, bounded per-turn work. Buffer caps C1C сохраняются; не использовать communicate/readall и бесконечную очередь events. Snapshot stage — одно последнее значение, candidate — не более одного immutable reply≤4MiB, decoder — один bounded frame. Контент не включается в repr/error/thread exception/log. Неиспользуемые буферы освобождаются по завершении/fault.

Control writer — отдельный небольшой сериализованный объект. Permit/Stop frames реально короче512bytes; при создании проверяется `PC_PIPE_BUF >= len(frame)` для каждого frame, nonblocking write атомарен. Seq увеличивается только после полной записи. Нет очереди старых permits и shared lock с data decoding. EAGAIN/short write/ошибка/cap exceeded — закрыть control writer и latch local fault; старый permit продолжает ограничивать G, EOF прекращает попытку. Stop пишет один stop, затем закрывает writer; при backpressure просто закрывает его. Повтор Stop idempotent. Закрытие и write выполняются под одним коротким lock, исключая fd-reuse race. Сам Stop не ждёт data thread или SQL.

Разрешение выдать candidate C1F требует одновременно:

- один корректный C1C result с ready/stages и exact spec digest, полный events EOF без хвоста;
- valid closed(clean,0,True)+status EOF, нормальный exit0 собственного G;
- отсутствие local/guardian Stop/fault; local D/L ещё действуют;
- затем C1F ставит `AttemptControl.mark_child_closed` и передаёт reply в **GuardedPublisher**, который независимо валидирует B1/B2/SQL.

Result+hang, result+nonzero exit, error+exit0, stdout tail, status без EOF, clean status при invalid result — не candidate. Валидный model error с nonzero exit после cleanup можно отобразить как соответствующую ошибку, но не как «замечаний нет». После exit допускается drain оставшегося data, не новый анализ: предел min(старые D/L, observed exit+2s). Нет EOF после этого — fault, без success. Physical cleanup может быть true при protocol failure; publication eligibility при этом false.

Driver никогда не вызывает SQL, C1A.reserve/settle или mark_child_closed сам. Его view — DTO, не capability; C1F принимает completion только от зарегистрированного owned driver. Stop, пришедший после уже выданного candidate, всё равно проходит C1A; судьбу in-flight COMMIT определяет C1B, не driver.

## 7. Owner/slot и повторный запуск

Точные API и файловые проверки — [D1 contract](d03-17c1d1-contract.md). Private canonical root заранее создаётся trusted desktop/test setup; C1D не определяет discovery пользовательского каталога. Lock names постоянны, не зависят от документа/run. Open через directory FD, no symlink traversal, regular0600/ownUID/nlink1, проверка inode. Никаких PID/секретов/документа в lock file. Не unlink/replace/chmod существующих чужих файлов ради успеха.

Порядок runtime.owner→analysis.slot. Flock с nonblocking exclusive; дубль FD/унаследованный reference относится к тому же lock, явный unlock снял бы его и у child. Поэтому только close. [Apple flock](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/flock.2.html).

S сохраняет свой slot до physical outcome **и SQL reconciliation**. C1D не знает SQL и не подделывает завершение этой части. C1F затем закрывает S reference и пробует отдельный open+lock того же inode, продолжая держать owner. Busy — живой holder/неразрешённая утечка; следующий claim/spawn запрещён. Probe success закрывается; следующая попытка всё равно делает новое reserve перед claim.

После потери G нет доверенного child exit_code. Когда G уже reaped, C1F разрешил SQL и новая независимая slot acquisition успешна, можно признать отсутствие holder и разрешить **новый** запуск; старый result не становится candidate и старый running attempt не продолжается. Пока slot busy — runtime_busy, без чужих kill. G всё ещё жив/неопределён — сначала control EOF и ожидание, нельзя пробовать «освободить» slot принудительно.

## 8. Ошибки и границы восстановления

| Cut point | Ожидаемое поведение |
|---|---|
| S умер до первого permit/GO | G не разрешает engine, initial lease/EOF прекращает bootstrap |
| S умер во время большого request или inference | Единственный control writer пропадает; G закрывает gate, TERM→KILL→wait |
| G умер до GO | M видит gate EOF; engine не импортирован; SQL результат не публикуется |
| G умер после GO, M способен исполнять Python | Gate reader прекращает M; S фиксирует отсутствие подтверждённого closed, не success |
| G умер после GO при native/GIL hang M | Orphan может жить и удерживать slot; следующий runtime_busy, без PID recovery |
| G и S умерли | Тот же fail-closed slot; OS broker/полное автоматическое восстановление не входят в C1D |
| M закончил до NOTE_EXIT registration | Поздняя регистрация либо безопасный failed bootstrap; не blind kill после reap |
| M result есть, G ещё не wait | Private candidate buffer; публикации нет |
| SQL terminal, M ещё жив | Slot остаётся занятым; terminal SQL не считается cleanup |
| Stop после C1A permit / lost SQL ACK | G останавливает compute независимо; C1B reconciliation сохраняет фактический результат |
| Model/caller не читает pipe | Nonblocking bounded IO; время и Stop продолжают действовать |
| Потерян wait ownership | Нет unsafe signal/restart; metadata-only fault, pending/busy |

Нет гарантии восстановления произвольных зависших OS kernel resources. Нет cleanup proof против pack, закрывающего служебный slot/порождающего escaped descendant. Не обещать unlimited docs/RSS или любой компьютер. Native Windows и реальный suspend/resume Mac — отдельные release gates; синтетический скачок часов проверяет decision logic, не работу драйверов/ядра после сна.

## 9. Разделение реализации и приёмка

| ID | Scope / paths | Обязательный выход |
|---|---|---|
| **D03-17C1D1** | `macos/__init__.py`, `_errors.py`, `_clock.py`, `_locks.py`; новая acceptance/own tests | [Выполнен](d03-17c1d1-result.md), gate3168+24; checked clock/owner/slot. Без guardian/model/SQL. [Контракт](d03-17c1d1-contract.md) |
| **D03-17C1D2** | Новые `macos/_ownership.py`, `_bootstrap.py`, `_guardian.py`, `_child_bootstrap.py`, `_fixture_child.py`, `_launch.py`, trusted standalone entry files; новые acceptance/fixtures | [Завершён](d03-17c1d2-finish-result.md), gate3226+24; дополнение Stop реализовано, исходные frozen tests сохранены |
| **D03-17C1D3** | Новые `macos/driver.py`, `_control_pipe.py`, `_data_pump.py`, `_driver_models.py`, новые acceptance/own tests | [Завершён](d03-17c1d3-result.md), gate3247+24; native parent transport/candidate gate, без SQL/HTTP/реальной модели |

D2/D3 перед своим implementation фиксируют exact callable API/allowed files/frozen acceptance на основании этого проекта; это обычная подготовка bounded цикла на Sol, повторного архитектурного выбора не требуется. Замороженные D1/D2 tests/контракты не переписываются для D3. Если потребуется изменить уже согласованную семантику, сначала отдельное уточнение, а не ослабление теста. root worker `__init__.py`/старые packages не править для удобства imports: использовать новый subpackage.

Обязательная acceptance matrix D2/D3:

- Независимые fake syscall scripts: NOTE_EXIT до Stop; exit между последней проверкой и TERM; EPERM/ESRCH с последующим exact wait и без него; ECHILD; KILL success без exit; bad event PID/filter; неверный wait; запрет любого signal после первого wait/reap. Отрицательная проверка вызовов Popen.poll/send_signal, shell/ps/PID adoption.
- Native late exit registration; живой TERM; ignored TERM→KILL; естественный exit без сигнала; post-result hang/nonzero/tail; missing prepared/armed/GO, partial/extra token, invalid control. Before/after каждого spawn/FD-transfer/GO cut point.
- Parent death во время request/inference, guardian death до/после GO, stalled model и orphan slot. Fault fixtures имеют независимое ограниченное естественное завершение/owned teardown в harness; тест не оставляет бесконечные процессы и не ищет процессы пользователя.
- Owner не наследуется; control/gate writer не утекает в M; FD counts стабильны после серии attempts/early failures. Inherited slot не освобождается после смерти S/G до выхода M; explicit LOCK_UN запрещён spy. Два independent runtimes/attempts не совпадают по ресурсу.
- Initial expired budget до spawn; equality D/L; late permit не оживляет; D change/seq/cap; rollback/overflow clock; simulated suspend >L/D и >grace. Native clock smoke; отдельная честная отметка physical sleep gate.
- Big request backpressure; stdout/stderr flood; 64KiB/64KiB+1 stderr; 6MiB/oversize/truncated wire; request EOF early; result без closed/G exit; private exceptions и bytes отсутствуют в logs. Stop не ждёт decoder/data lock/SQL.
- Candidate только после совокупного proof; cleanup true при invalid payload не превращается в ML success. Slot держится внешним S до явного caller release; fixture не помечается real analysis.

Каждый D1/D2/D3: новый contract/acceptance freeze → red → source → targeted/own/native → `bash scripts/check.sh` → read-only DB baseline comparison → result/local commit. Native Mac skip/error не выдаётся за native pass. Не менять runner/tasks/progress/dependencies/V10/старые tests. Нет main migration, чтения secrets/archive, Word, модели или push.

## 10. Проверенные основания и дальнейшая команда

Предыдущий probe C1C подтвердил поздний NOTE_EXIT (5/5), inherited flock и setsid; не доказал live kill. В этом design-cycle новый synthetic probe `.runtime/d03-17c1d-design-probe.json` отдельно подтвердил: natural exit0 без сигналов; live TERM→wait(-15); ignore TERM→KILL→wait(-9). Все три child получили NOTE_EXIT и reaped. Native timebase125/3, integer ns увеличиваются и укладываются в signed63. Ни real suspend, ни production guardian этим не проверены. Старый EPERM не объявляется permission blocker; результат нового probe не доказывает точную причину старого errno.

**Далее Sol 6.1 High: D03-17C1D1, затем D2 и D3 отдельными циклами.** Дизайн завершён, реализации D нет. Прежняя одна строка D разделена на три (+2); самостоятельный остаток теперь ориентировочно **30–45 циклов** вместо28–43. Это уточнение размера проверяемых работ, не новые функции и не гарантированный потолок. Полный DOCX, C1E/F/C2, лицензия, desktop/поставка/финальная проверка впереди; работа Ани/Артёма в этот счётчик не включена.

Актуализация2ноября: [D1](d03-17c1d1-result.md), [D2](d03-17c1d2-finish-result.md), [D3](d03-17c1d3-result.md) завершены, итоговый gate3247+24. **Далее C1E Windows exact ownership/IO design на Astra6 High**, затем реализация Sol по отдельному contract/freeze/red. Остаток27–42. Native Windows/real model не объявлены готовыми; предыдущий абзац — историческая команда на границе исходного design-cycle.
