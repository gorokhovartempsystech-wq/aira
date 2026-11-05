# D03-17C1E — Windows: владение процессами и обмен данными

**Передача 3 ноября после C1F design:** [проект supervisor/recovery](d03-17c1f-design.md) и [контракт F1](d03-17c1f1-contract.md) подготовлены; следующая реализация на Sol6.1 High. Durable arm до create, drained после physical/own-I/O proof, quarantine при потерянном proof. Verified boot provider пока отсутствует: Windows production/recovery gate остаётся открытым. E1–E4 source/tests unchanged; самостоятельный остаток28–43 после разбиения F на три цикла. Предыдущие записи ниже — история handoff.

**Текущий статус, 3 ноября:** [E4 завершён в available границах](d03-17c1e4-result.md): итоговый full3508passed+24subtests/41native skipped,exit0; main V8 и468code/test/config hashes unchanged. Гонка подготовки frozen acceptance устранена ожиданием owner release, все44 assertions сохранены; source unchanged. Следующий шаг **C1F design на Astra6 High**, [handoff](d03-17c1f-preflight.md). Native Windows и durable recovery остаются обязательными gates; весь C1E/production Windows не принят. Остаток26–41 после завершения уже учтённого E4.

2 ноября 2026, Astra 6 High, по прямому запросу Никиты. Основание — проверенный macOS D3 `5796c16`, [handoff](d03-17c1d3-result.md), [C1](d03-17c1-design.md), неизменные C1A/B/C. F06–F08/F12; F02 только как будущая точка явного запуска runtime. Это техническое уточнение Windows-эскиза C1 §5, не новая продуктовая спецификация и не реализация Windows.

**Уточнение после E1/E2, 2 ноября:** [точный контракт E3](d03-17c1e3-contract.md) определяет creation outcomes, retained holder, threads и неизвестный pre-return исход. Он заменяет сильное утверждение этого эскиза об автоматическом cleanup во всех cut points. JOB_LIST сохраняется; caller death без наблюдаемого возврата не даёт cleanup ACK. Автоматическое restart recovery этой ветки требует C1F durable crash fence и отдельного gate. Frozen E1/E2 не меняются.

**Уточнение после E3, 2 ноября:** [точный контракт E4](d03-17c1e4-contract.md) определяет три I/O owners, startup gate и synchronous public renew через bounded command/receipt. Локальный L увеличивается при принятии caller полного своевременного receipt; очередь или completion без этого не ACK. Stop — R/H event и owner close, без дополнительного stop frame. Candidate требует также полного request+EOF; resources_closed, physical proof и SQL ACK различаются. Это уточнение нового parent driver, без изменений frozen E1–E3. Реализация E4 ещё не начата; следующий режим Sol6.1 High.

[Результат E4 design](d03-17c1e4-design-result.md): full3442passed+24subtests,26native skipped,76warnings,396,92s,exit0;460 source/test/config hashes и main V8 unchanged. Контракт готов, acceptance/freeze/red/source ещё впереди. Остаток27–42 без новых ID, после реализации E4 следующий архитектурный gate — C1F на Astra6 High.

## 1. Выбранное решение

**Создавать процессы сразу с назначенным Job через `PROC_THREAD_ATTRIBUTE_JOB_LIST`.** Отдельный `CreateProcess → AssignProcessToJobObject` не используется даже как fallback. Отсутствие нужной возможности, конфликт с внешним Job или ошибка атрибута означают безопасный отказ. До успешного создания нет пригодного child; после успешного создания он уже относится к Job. Остаётся `CREATE_SUSPENDED` для проверки handles/membership до запуска bootstrap, но не для устранения assignment gap. Microsoft документирует JOB_LIST начиная с Windows 10; это API-основание решения, а не подтверждение нашей реализации. [Create attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute).

Отдельный разбор Microsoft подтверждает именно проблему orphan при crash между suspended create и assignment и применение JOB_LIST для её устранения. Это основание выбора вместо непроверенного handoff запасного process HANDLE. [Разбор окна создания](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812).

Техническая первая проверочная конфигурация — **64-bit CPython на Windows 11 x64, локальный NTFS**. Win32/x86, ARM64/emulation, Windows 10, Server, SMB/ReFS/FAT не объявляются поддержанными этим циклом. Это ограничение первой реализации/приёмки; окончательная продуктовая матрица ОС и железа остаётся открытой в current-product-scope.md. Не подменять её маркетинговым обещанием. Проверять возможности API, не доверять одному номеру ОС.

Используются два неназванных Job:

| Job | Единственный владелец HANDLE | Участники | Предел |
|---|---|---|---|
| `J_attempt` | supervisor S | guardian G и model M | `ACTIVE_PROCESS=2`, `KILL_ON_JOB_CLOSE` |
| `J_model` | guardian G | только model M | `ACTIVE_PROCESS=1`, `KILL_ON_JOB_CLOSE` |

S сам не входит в J_attempt. G создаётся сразу в J_attempt. M наследует цепочку Job своего родителя G и при creation получает новый J_model; он становится вложенным в J_attempt. Ни один Job не разрешает breakaway/silent breakaway; CREATE_BREAKAWAY_FROM_JOB и UI limits не используются. Если внешняя среда не допускает такую иерархию — отказ без повторного запуска с ослабленными flags. Документированное наследование цепочки и вложенность дают основу этой схемы; фактическая совместимость creation attributes проверяется нативными тестами. [Nested jobs](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs).

J_attempt HANDLE не попадает в G/M; J_model HANDLE не попадает в M/S. Членство в Job само по себе не создаёт пользовательскую копию его HANDLE. Закрытие последнего Job HANDLE инициирует прекращение связанных процессов. Это основание containment уже созданной группы, но не runtime proof pre-return исхода при смерти caller; точная неизвестная ветка — E3 §1/§2. Успешная команда kill или закрытие HANDLE не подтверждают уже завершившийся cleanup. [Job lifetime](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

Только trusted threads-only pack. Job active limit — дополнительная защита, не sandbox против того же OS user/администратора, не разрешение на WMI/службы/произвольные descendants. C1 использует bounded synthetic fixture, не веса/реальный engine.

## 2. Время, owner и execution slot

`GetTickCount64()*1_000_000`, integer checked signed63, равные readings допустимы, обратный ход/ошибка sticky. Используется непосредственно Win32 API: не .NET TickCount, не wall clock, не portable monotonic fallback. Этот clock учитывает сон/гибернацию. C1A уже вычел guard50ms; Windows повторно его не вычитает. D закреплён, L≤D и максимум15s от conservative ACK anchor. [Windows time](https://learn.microsoft.com/en-us/windows/win32/sysinfo/windows-time).

Wait timeouts — только wakeup: современные Win32 waits не включают сон. После любого wakeup и **до** frame/GO/renew/candidate читать clock и применять expiry; кусок wait≤100ms. Нельзя превращать wait300000ms в доказанный пяти-минутный deadline. Физический suspend/resume — отдельный обязательный native case. [Wait semantics](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject).

Отдельный private local root, `runtime.owner` и `analysis.slot`, pre-existing root. Owner — только S. Slot reserve до SQL claim, копии того же file object у S/G/M. `CreateFileW` с read/write, **share mode0**, без truncate/delete-on-close; inherited/duplicated HANDLE сохраняет reservation. Независимый новый open после закрытия своей копии доказывает только отсутствие остальных reservation holders. PID-файл/abandoned mutex/снятие lock отдельной командой не используются. [Sharing](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew), [DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle).

Точные root/DACL/reparse/identity/error/API правила — в [контракте E1](d03-17c1e1-contract.md). C1F освобождает S slot лишь после physical cleanup **и** SQL reconciliation, а также завершения собственных pending I/O. Probe не подтверждает SQL; result/COMMIT не подтверждает process exit. Новый S сначала owner, затем независимый slot и recovery barrier; для потерянного create outcome дополнительно обязателен durable crash fence из E3 §2, одного SQL recovery недостаточно. Старые PID/HANDLE numbers не восстанавливать из файлов.

## 3. Передача HANDLE и создание процессов

Все обычные HANDLE non-inheritable. На время одного create делать отдельные temporary inheritable duplicates только разрешённых объектов, передавать через `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`, `bInheritHandles=TRUE`; originals не переключать в inheritable. Один внутренний spawn mutex в процессе; все AIRA launch paths обязаны использовать explicit allowlist. После CreateProcess закрыть temporary duplicates в parent на любом исходе. Модульное ограничение не обещает защитить от стороннего concurrent launcher с blanket inheritance в том же процессе — такой launcher не допускается в desktop bootstrap. [Handle list](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute).

| Ресурс после handoff | S | G | M |
|---|---|---|---|
| runtime.owner/root pins | владеет | нет | нет |
| analysis.slot | владеет | duplicate | duplicate |
| J_attempt / G process HANDLE | владеет | нет | нет |
| J_model / M process HANDLE | нет | владеет | нет |
| control S→G | write | read | нет |
| status/armed G→S | read | write | нет |
| ordinary-stop / hard-abort events | signal | wait-only | нет |
| request S→M / events M→S | write/read | только до M-create | read/write |
| prepared M→G / gate G→M | нет | read/write | write/read |
| diagnostics M→G | нет | read | synchronous write |

Primary thread HANDLE хранит создатель только до единственного `ResumeThread`, закрывает после проверки возвращённого previous suspend count=1. G/M process HANDLE сохраняется до proof и final close. Никаких OpenProcess по PID, taskkill, console Ctrl+C, window messages или model-side process enumeration. Retained HANDLE не переиспользуется после close.

`CreateProcessW`: absolute trusted executable, mutable correctly Windows-quoted command line, Unicode double-NUL environment, fixed trusted cwd, `EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW`. Entry из trusted installation/source fixture, Python `-I -B`; пользовательские executable/args/env запрещены. Буферы attribute list, job/handle arrays и security descriptors живы до завершения create и DeleteProcThreadAttributeList. Process/thread security не создают наследуемые returned handles. [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw).

Environment строится заново: SystemRoot/WINDIR из явного OS location query, фиксированные Python/locale settings при необходимости. Нет наследования environment, PATH/proxy/PG*/API keys/PYTHONPATH/PYTHONHOME. TEMP/TMP не нужны synthetic fixture; если real pack потребует scratch — отдельный C2 contract, не plaintext request files. Стандартный stdin — owned NUL read; stdout/stderr модели — bounded diagnostic channel, не wire. G stdout/stderr — NUL. Wire использует отдельные raw HANDLE с собственным overlapped IO; не передавать overlapped handles в Python CRT buffered stdin/stdout. Diagnostic writer M synchronous, reader G overlapped; блокировка записи не мешает G kill. Не сохранять diagnostic bytes, только счётчик≤64KiB; превышение H, включая tail после выхода.

## 4. Startup и аварийные переходы

1. S валидирует/detaches identity, budget, request/spec, резервирует caller-owned slot; создаёт связанные pipe endpoints/events, J_attempt и устанавливает/checks limits **до** G create. Любая ошибка до G — закрыть только собственные resources.
2. Create G с JOB_LIST=[J_attempt], проверить IsProcessInJob(retained G,J_attempt), затем ResumeThread. При ошибке/неожиданном suspend count не продолжать: terminate owned J_attempt, ждать retained G и job count. S death закрывает его Job HANDLE; если create outcome не был получен, E3 сохраняет unknown без обещания уже завершённой очистки. Нет ветки «assign позже».
3. G стартует без engine/SQL. Проверяет inherited handles/types/roles/binding, initial continuous D/L и один C1C permit seq0 до M creation. Нет permit до начального L — остановка без M. Начальные D/L передаются trusted launch config для ограничения самого bootstrap.
4. G создаёт J_model, limits/readback, pipes prepared/gate/diagnostics. M создаётся с JOB_LIST=[J_model] в унаследованной цепочке J_attempt. Проверить own IsProcessInJob(M,J_model); failure→terminate J_model/close fallback, no resume/GO. Job attachment выполняется как часть create.
5. Resume M ровно один раз; M ещё не импортирует fixture/engine. Bootstrap принимает только ожидаемые handles/clock, начинает gate watcher, отправляет exact prepared token+EOF. G проверяет token+EOF и budget/Stop, отправляет GO token, затем armed token+EOF в S. Отдельные bootstrap channels как у C1D, **не изменения frozen C1C wire**. Нет request delivery до armed+EOF.
6. S повторно проверяет budget/Stop, отправляет один run frame, завершает writer. M требует полный run+EOF и spec digest, затем импортирует fixture. До GO действует начальный D/L; после GO watchdog G — authority, M watcher лишь cooperative помощь при EOF, не гарантия против GIL hang.

Отмена до GO отменяет ожидание prepared/armed: не ждём отсутствующего ACK, не запускаем engine. Уже обнаруженный malformed input остаётся H; отсутствие/допустимый partial prefix отменённого bootstrap не создаёт H само по себе. Unrequested early M exit до GO — H. Никакого retransmit GO/Resume/нового процесса в той же попытке.

| Cut point | Действие/доказательство |
|---|---|
| G creation/Resume failure | J_attempt retained у S; terminate+G wait+count0 либо blocked |
| S killed при create G, до permit, после GO | OS last-close containment; без retained evidence новый S не подтверждает cleanup по slot+SQL. Unknown pre-return/restart — E3 §1/§2 и обязательный C1F gate |
| G killed во время M create или при M GIL hang | OS закрывает J_model; S прекращает outer Job и ждёт G/count0; отсутствие M proof не восстанавливается, result запрещён |
| M suspended / prepared отсутствует | expiry/Stop приводит к terminate J_model; не ждать Python handler |
| M прислал result и завис | result provisional; deadline/Stop cleanup; candidate отсутствует |
| Terminate/Query/Wait/Close error | sticky H, отсутствие нужного proof не заменять success; никаких PID fallback |

## 5. Stop, завершение и result proof

Два manual-reset unnamed event, никогда не ResetEvent в рамках attempt: **ordinary-stop** (R) и **hard-abort** (H). S владеет signal rights, G наследует только SYNCHRONIZE. `.stop(reason)` фиксирует local latch; для обычных C1C reasons сигналит ordinary event, для `protocol` — hard event. Закрытие control при fault даёт дополнительный EOF. G проверяет events и clock до обработки data/control. Native events — out-of-band abort primitives, не новая бизнес-семантика или wire ACK. Причина Stop остаётся у S/C1A/SQL; G нужен класс R/H. Полученный корректный stop frame/EOF также поддерживается. Уже выявленный H не превращается в R.

G закрывает gate для cooperative Stop и немедленно запрещает GO. При живом M ждёт не более2s continuous grace; затем ровно один TerminateJobObject(J_model, fixed nonzero code). При H/clock fault можно terminate сразу. Job terminate success — только запрос. Для closed status обязательны **WaitForSingleObject(M,0)=WAIT_OBJECT_0**, успешный GetExitCodeProcess и QueryInformationJobObject(J_model).ActiveProcesses=0. Job notification или сигнал самого Job не заменяют это сочетание. Ожидание ограничено; при неизвестном результате G не отправляет closed(cleanup=True), закрывает J_model/выходит с ошибкой. [Job termination](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject).

Для Windows не переносить macOS-specific послабление EPERM/ESRCH. Ошибка terminate/query/wait — H. Подтверждённый exit без H: R→stopped, без R и code0→clean, иначе crashed. При H и physical proof→crashed; без proof нет trustworthy closed. DWORD exit преобразуется в signed32 (`u` при u<2**31, иначе `u-2**32`) для C1C без изменения schema. Сначала wait, потом code: 259 после signalled — настоящий необычный код, не бесконечный STILL_ACTIVE. [Exit codes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess).

S дополнительно проверяет G process signalled+actual exit code и J_attempt.ActiveProcesses=0. Это независимый контроль всей группы, но **не замена** missing G status/M wait. При G crash или потере status `cleanup_confirmed=False`, phase=blocked, candidate отсутствует даже при пустом outer Job. Slot probe/SQL reconciliation необходимы для C1F recovery, но не снимают unknown creation без дополнительного proof/fence по E3 §2; driver не угадывает старый outcome. `.close(timeout=5)` при зависшем G инициирует terminate своего J_attempt; возвращает False, если к timeout G wait/job count0 или I/O quiescence ещё нет, сохраняет record/handles для последующего ожидания. True означает закрытие собственных ресурсов driver, не добавляет отсутствующее M evidence; unknown creation остаётся False. Stop не ждёт этих5s. На normal path Job закрывается после проверок; emergency abandon closing last job инициирует teardown, но теряет возможность query и не выдаёт cleanup confirmation.

Candidate допускается только вместе: armed+EOF, valid C1C ready/stages/result+eventsEOF, valid closed(clean,0,True)+statusEOF, G exit0, S outer Job count0, live D/L, no Stop/H. Repeated candidate — те же bytes, не inference. Late Stop отзывает выдачу, но уже переданные C1F bytes защищают C1A/B. Error frame/tail/nonzero/unknown exit/diagnostic flood/result+hang не success. C1E не вызывает SQL; frozen C1A/B продолжают различать OS cleanup, permit и durable COMMIT.

## 6. Windows pipe transport

Все data/control/bootstrap channels — заранее соединённые **односторонние local named-pipe pairs**, после setup передаются только HANDLE. Случайные128bit names, один instance, FILE_FLAG_FIRST_PIPE_INSTANCE, PIPE_REJECT_REMOTE_CLIENTS, explicit protected DACL current SID/SYSTEM/Administrators. Не default ACL, не общедоступный постоянный server/порт, не filesystem payload. Обе стороны создаёт один trusted process до handoff; никаких reconnect/повторного ожидания неизвестного клиента. [Pipe security](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights).

Byte stream/PIPE_WAIT + FILE_FLAG_OVERLAPPED; не PIPE_NOWAIT и не POSIX PIPE_BUF/select. Parent создаёт overlapped server, начинает ConnectNamedPipe, открывает свой client с нужными read/write rights, завершает connect (в том числе корректный ERROR_PIPE_CONNECTED); до success payload не передаётся. Проверяет connected peer PID равен текущему процессу до передачи, SID ограничен DACL; collision/foreign connection — fail closed без повторного использования name. Setup timeout≤min(L,now+2s), однократная попытка. Requested pipe buffers64KiB, но память/очереди ограничиваются приложением независимо от фактической квоты ядра. [Modes/connect flags](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea).

Каждый endpoint имеет максимум одну pending operation, собственные OVERLAPPED/manual-reset event и стабильный buffer≤64KiB. No readall/communicate/FlushFileBuffers/WaitNamedPipe(INFINITE). Read/write partial учитываются явно, zero progress reject кроме подтверждённого EOF; ERROR_BROKEN_PIPE — EOF, для незавершённого frame без принятой остановки protocol fault. Общий C1C decoder caps/sequence/hash/EOF unchanged; большой run/result дробится на chunks≤64KiB, один provisional candidate≤4MiB, bounded transient copies, одна latest stage.

`CancelIoEx` **не означает**, что можно освободить buffer/OVERLAPPED/event. После cancel надо дождаться terminal GetOverlappedResult(False): normal completion, aborted либо error. ERROR_NOT_FOUND тоже не completion proof. До terminal completion не close HANDLE/event, не reuse memory; остановка admission/retained record при зависшем cancellation. Native API failure не маскируется retry по переиспользованному int. [CancelIoEx](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelioex), [Completion](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-getoverlappedresult).

Pending records strongly retained до completion даже при потере caller reference; registry bounded64 per process, admission до native submission, исчерпание→safe failure. Endpoint close сначала cancellation, затем nonblocking reap; False сохраняет pending record. Explicit owner loop завершает их; никаких бесконечных finalizer threads/новых попыток поверх незавершённого cleanup. Slot удерживается C1F до quiescence. Registry — техническая страховка lifetime, не фоновый scheduler.

**Control writer не ждёт data pump.** Один маленький frame≤4KiB+4bytes header, отдельная сериализация writer и overlapped operation, без очереди permit. Immediate completion принимается; при pending ждать только до min(now+50ms,old L,D), без удержания Stop/metadata mutex. `.stop` ставит latch/event независимо от этого ожидания. Renew True лишь после full completion, повторного чтения clock и проверки old L/no Stop; short/error/timeout→H+hard-abort+cancel/reap, без retry/увеличения L. Seq/caps512frames/1MiB учитывают все действительно отправленные frames, в том числе completed frame при одновременном Stop; следующего permit после Stop всё равно нет. Это bounded delivery policy, не утверждение атомарности Windows pipes. G сравнивает old L с now **до** decode buffered permit. Cancelled valid control prefix при already R не становится ложным malformed; уже обнаруженные ошибки сохраняются. Даже если partially delivered permit позже прочитан, hard-abort/old L не позволяют продолжить попытку.

Один data-pump thread у S, bounded wait set≤32 handles, per turn≤64KiB на lane и≤256KiB суммарно, clock/control сначала; no polling spin. У G один loop с такими же границами, плюс независимость от model GIL. Events/metadata mutex не охватывает decode, SQL, wait или join. Handles, по которым другой поток ещё ждёт, не закрывать; Stop только сигналит свои events и координирует control cancellation. Tail drain≤2s после первого closed/exit, не бесконечное ожидание EOF. Cleanup time не даёт новых model budget/permit.

## 7. Циклы реализации и приёмка

| Цикл | Ограниченная ответственность | Что фиксируется перед source |
|---|---|---|
| **C1E1** | Native ABI, clock, private root и owner/slot HANDLE | [Готовый точный контракт](d03-17c1e1-contract.md), новая acceptance/freeze/red |
| **C1E2** | Connected pipes, events, overlapped lifetime/cancel, bounded IO ports | Exact API/state transitions/allowed new files; без process/model/SQL |
| **C1E3** | Два Job, atomic create, bootstrap G/M, cleanup/status | Exact launcher/guardian API и crash-cut acceptance; synthetic fixture |
| **C1E4** | S driver/control/data pump, composite candidate, lifecycle fault matrix | Windows port API и E2/E3 integration; без C1F/SQL/real engine |

Нельзя переносить macos.py целиком или рефакторить проверенные C1A/B/C/D ради common base. Новые модули в `ara.docx_analysis_worker.windows`, windows-only imports lazy, публичные worker exports неизменны. Следующие exact contracts могут уточнить названия private files/DTO, но выбранные ownership/proof/limits не ослабляют. D1-style E1 contract готов сейчас; E2–E4 freeze последовательно на Sol перед соответствующим source. Нет причины заранее дробить их ещё; новое противоречие — отдельный handoff, не подгонка frozen acceptance.

Обязательная матрица: normal/error/tail/flood/nonzero/259/NTSTATUS; Stop до create/Resume/GO/во время request8MiB/result; missing/extra prepared/armed; wake после L/D; pending/cancel race и lost completion; G/S killed при каждом startup cut; simultaneous S/G death; exact inherited allowlist/no Job/owner leak; несовместимый external Job; дочерний spawn rejected; repeated100 attempts без роста HANDLE/thread count; после выхода доступен independent slot. PID используется только test observation из собственного retained process, не kill authority. Fixture watchdogs ограничены по времени; тестовая очистка через own Job/HANDLE, не поиск чужих процессов.

На Windows обязательны реальные CreateProcess/JOB_LIST/nested Job/NTFS/IO tests и отдельный suspend/resume. Fake ABI/ports на Mac проверяют логику/границы, **не** поведение ядра Windows. Полный `bash scripts/check.sh` выполняется в текущем Mac окружении; targeted native Windows suite запускается отдельно через установленный project Python. Старые Mac-oriented tests не переписываются ради запуска всего repo на Windows. Полная Windows desktop/installer integration позже остаётся самостоятельным gate.

В каждом implementation result раздельно: доступные проверки, native cases passed/skipped/pending и точная конфигурация. При недоступной Windows можно сделать проверяемый код/portable gates и продолжать независимые циклы по разрешению Никиты; Windows release gate остаётся **pending**, C1E не объявлять полностью принятым. C1F wiring не выбирает непроверенный Windows driver как production-ready по одному platform string.

Первый шаг после этого дизайна — **Sol 6.1 High, D03-17C1E1**. Новых продуктовых ответов не требуется. Самостоятельный остаток **30–45 циклов**: прежние27–42 учитывали C1E одной строкой, здесь она уточнена до четырёх (+3). Дизайн повторно не считается; новых функций нет. Native environment/Аня/Артём не считаются выполненной самостоятельной работой. Это ориентир, не потолок.

E1 available code/portable gate реализован 2 ноября: [результат](d03-17c1e1-result.md),3340passed+24subtests,7native Windows skips,exit0; main V8 unchanged. **Далее E2 на Sol6.1 High** по [собственному контракту](d03-17c1e2-contract.md), freeze/red до source. Native Windows gate по-прежнему pending; самостоятельный остаток29–44.

E2 available implementation завершён: [результат](d03-17c1e2-result.md), full3378passed+24subtests,10native Windows skipped,exit0; main V8 unchanged. Далее **E3 Job/guardian/bootstrap на Sol6.1 High** с отдельным exact contract/freeze/red. Остаток28–43; нативная Windows приёмка E1/E2 остаётся pending.

**Preflight E3, 2 ноября:** до source обнаружено недостаточно обоснованное сильное обещание pre-return cleanup: смерть caller внутри CreateProcessW и last Job close требуют отдельного разбора. Это не observed native bug. [Вопрос/источники/передача](d03-17c1e3-preflight.md). **Сейчас Astra6 High для уточнения E3 startup proof/recovery**, затем Sol implementation. E1/E2 завершены в available границах, E3 не начат, остаток28–43 unchanged. Исходные §1/§4 — проектное намерение, не подтверждённая native гарантия этого cut point.

**Разбор E3 завершён, 2 ноября:** [контракт](d03-17c1e3-contract.md) сохраняет JOB_LIST, различает failed/created/unknown и запрещает автоматическое снятие quarantine; unknown restart передан в обязательный C1F durable recovery gate. Exact holder/ABI/ownership/IO-thread/acceptance определены, source/acceptance E3 ещё не созданы. **Далее Sol6.1 High — D03-17C1E3**, freeze/red до реализации; остаток28–43 без изменений. Pre-return crash test только в disposable Windows VM, без лишнего Job HANDLE у harness; native gate pending.

[Результат проектирования E3](d03-17c1e3-design-result.md): full3378passed+24subtests,10native skipped,77warnings,375,58s,exit0; source/tests и main V8 unchanged. Это регрессия существующего кода, не приёмка ещё не написанного E3.

**E3 available implementation завершён на Sol6.1 High:** [результат](d03-17c1e3-result.md), frozen acceptanced948ca1, согласованное дополнение прав pipe a32c39e. Job/retained create/bootstrap/guardian/fixture, caller slot не освобождается, unknown fail-closed. Targeted E1–E3:195passed/26native skipped; full **3442passed+24subtests,26skipped,74warnings,402,69s,exit0**,460files unchanged, main V8 unchanged. E2 writer получил только FILE_READ_ATTRIBUTES по прямому разрешению Никиты; старые tests неизменны. Native Windows gate pending, C1E целиком не принят. **Далее Astra6 High — exact E4 parent driver/control/pump ownership contract** по [handoff](d03-17c1e4-preflight.md), затем Sol6.1 High implementation. Остаток27–42, новых ID/циклов не добавлено.
