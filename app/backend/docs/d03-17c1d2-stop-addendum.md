# D03-17C1D2 — уточнение Stop, ошибки сигнала и подтверждённого выхода

1 ноября 2026, Astra 6 High, по прямой команде Никиты разобрать [конфликт D2](d03-17c1d2-result.md). Нормативное техническое дополнение к [замороженному контракту D2](d03-17c1d2-contract.md), freeze `9afce73`, и §5–6 [проекта C1D](d03-17c1d-design.md). F06–F08/F12, продуктовый объём прежний. **Разбор завершён; runtime исправление выполняет следующий Sol6.1 High.** Это продолжение того же D2, не новый цикл в оценке.

## 1. Решение и область замены

**Обычная остановка с подтверждённым exit может иметь `exit_kind=stopped`, даже если отправка TERM/KILL вернула EPERM/ESRCH/EINTR.** Ошибка сигнала остаётся в монотонной диагностике. До exact wait `cleanup_confirmed` не появляется; при самостоятельном сбое наблюдателя/protocol/clock результат остаётся crashed или unknown. `stopped` не разрешает clean candidate, SQL publication или немедленный повторный spawn.

Уточнение заменяет только неоднозначное использование общего fault в исходном D2:

| Исходное правило | Точное правило после дополнения |
|---|---|
| При signal error устанавливается fault latch | Сохраняется общий sticky `OwnedChild.fault`; дополнительно различаются `signal_error` и `hard_fault`. Общий fault никогда не очищается ради stopped |
| Любой fault приоритетнее stopped | Самостоятельный `hard_fault` приоритетнее stopped; ожидаемая ошибка операции signal при ordinary Stop и exact wait не обязана означать crashed |
| Нет GO при exit → startup failure | Если ordinary Stop уже принят до завершения startup, недополученный ACK/отсутствие GO — следствие отменённого старта; сами по себе не создают новый hard fault. Уже обнаруженные bootstrap faults сохраняются |

Frozen contract/acceptance `9afce73` остаются побайтово прежними как baseline. По этим трём уточнениям применяется **это дополнение**, остальные требования C1D/D2 действуют. Ни старые тесты, ни ML wire, ни C1A/B/D1/DDL не меняются. Это разрешённое текущим запросом архитектурное уточнение, а не изменение критериев ради объявления готовности: D2 остаётся незавершённым до новой additive acceptance и полного green gate.

## 2. Почему errno недостаточно

В текущем WIP есть два преобразования общего признака в ошибку guardian: `if child.fault: fault = stopped = True` в loop и `fault = fault or child.fault` перед closed. Поэтому даже подтверждённый выход после обычного Stop неизбежно получает crashed, если signal вернул ошибку. Исправление только последнего ternary недостаточно: первый переход уже навсегда потерял происхождение fault.

Наблюдение native probe: gate EOF → killpg(SIGTERM)/errno1 → exact wait/exit74. Код74 используется watcher также при других отказах, поэтому он **не является доказательством причины выхода** и не получает специальную ветку в classifier. Наличие или отсутствие именно errno1 тоже не является exit proof.

Документация Apple перечисляет EPERM/ESRCH/EINVAL как ошибки операции killpg. [Apple killpg](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/killpg.2.html). В опубликованном XNU group iteration отбрасывает SZOMB, а отсутствие найденного подходящего процесса может возвращать EPERM. Это объясняет возможность такой гонки, не устанавливает причину каждого EPERM или версию установленного ядра. [Apple XNU killpg1](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_sig.c#L1612-L1624).

Подтверждение завершения даёт wait конкретного прямого child с terminal status; WNOHANG=0 сообщает отсутствие такого подтверждения. NOTE_EXIT используется для закрытия права сигналить, но финальный exit_code всё равно берётся из wait. [Apple wait](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/wait.2.html).

Решение не требует установить, был ли EPERM вызван zombie race или настоящим ограничением прав. Даже если отправить сигнал действительно не удалось, последующий exact wait может доказать, что требуемое состояние «процесс больше не работает» уже достигнуто. До этого evidence отказ остаётся pending; syscall не повторяется альтернативным способом.

## 3. Независимые факты

Все факты принадлежат одному owned attempt и обновляются одним guardian loop. Readonly свойства не принимаются из client DTO. Утраченные права не восстанавливаются при новом evidence.

| Факт | Значение / источник | Монотонность |
|---|---|---|
| `R = stop_requested` | Обычное прекращение compute: valid Stop(user/deadline/lease/storage/shutdown), корректный EOF control, истечение D/L по исправным часам | Только False→True |
| `S = signal_error` | Один вызов killpg выбранному owned group завершился OSError | Только False→True, сохраняется и после wait |
| `H = hard_fault` | Ошибка protocol/bootstrap/clock/kqueue/wait/FD/lifetime/неожиданной native операции | Только False→True; поздний Stop не маскирует |
| `W = exited` | Exact waitpid(owned PID,WNOHANG) вернул этот PID и WIFEXITED/WIFSIGNALED; сохранён реальный exit_code | Только False→True |
| `L = lost` | Достоверное wait ownership потеряно/ответ несовместим с record | Только False→True; запрещает closed с proof |
| `signals_open` | Ещё разрешено обращаться к pinned owned group | Только True→False, никогда обратно |

На уровне OwnedChild добавить readonly `signal_error`, `signal_errno`, `hard_fault`; сохранить readonly `fault`, `exited`, `exit_code`, `lost`. `fault = signal_error or hard_fault or lost` — совместимый sticky aggregate для старых tests и запрета admission. Состояние хранится в private fields; нельзя назначением публичного свойства подделать wait proof. `signal_errno` — None либо фиксированное `eperm/esrch/eintr/unexpected`; не сохранять str(error), path, payload, произвольные подробности. Один record на attempt, никакой растущей истории.

`H` guardian = собственный hard_fault OR child.hard_fault OR child.lost. **Нельзя присваивать ему child.fault** или выводить hard_fault из signal_error. Отдельный `teardown_requested = R or H or S` управляет прекращением вычисления. Принудительный cleanup из-за protocol/clock fault не создаёт ordinary R.

### Источники классифицируются по операции, не только по номеру ошибки

- OSError **именно вокруг killpg** с EPERM/ESRCH/EINTR → S=True, закрыть signals; H этим событием не создаётся. EINTR включён как консервативная политика неопределённого исхода операции, не обещание, что macOS всегда возвращает его из killpg.
- Любой другой errno/отсутствующий errno, неверный signal number или unexpected exception в signal path → S=True **и** H=True. EINVAL не маскируется как нормальная Stop race; valid production signals по-прежнему только TERM/KILL.
- EPERM/ESRCH/EINTR из kqueue/open/clock/wait не попадают в signal bucket. Это H; потеря/ошибка wait — L по прежней fail-closed политике D2. В частности, wait EINTR не превращается в разрешение повторять signal.
- Clock fault/rollback/overflow, malformed control/partial control EOF, ошибочный bootstrap token, stderr overflow/ошибка drain, потеря FD/ownership → H. Valid Stop с `reason=protocol` тоже несёт сообщение о protocol fault и создаёт H, а не ordinary R.
- Storage/shutdown Stop прекращают compute управляемо (R); их пользовательский итог определяет backend/SQL. Guardian не превращает storage error или timeout в пользовательское «отменено».
- Отсутствующий ACK/GO после уже принятой ordinary отмены startup сам по себе не H (§6). Уже замеченный malformed ACK никогда не очищается.

Сводный fault совместим с текущим `test_signal_error_is_not_cleanup_and_not_retried`: после signal failure он остаётся True при W=False, а также после W=True. Возможность stopped означает другое значение transport outcome, не удаление факта ошибки.

## 4. Точный выбор closed

В `_guardian.py` добавить private pure helper:

`_closed_kind(*, exited:bool, lost:bool, exit_code:int|None, stop_requested:bool, hard_fault:bool, signal_error:bool) -> str|None`.

Это функция классификации **внутренних наблюдений**, не capability/API подтверждения завершения. Caller берёт факты только из своего retained OwnedChild и guardian latches. Boolean inputs exact bool; exit_code — exact signed32 int или None; invalid local types → sanitized MacRuntimeError(runtime_unavailable), без closed. `exited=True` с None code или lost=True не содержит пригодного proof → None. Правила в следующем порядке:

| W / L | H | R | S | Exit code | Результат |
|---|---|---|---|---|---|
| W=False либо L=True либо code=None | любой | любой | любой | — | None: нет closed/cleanup proof |
| W=True, L=False | True | любой | любой | реальный | crashed |
| W=True, L=False | False | True | любой | реальный | stopped |
| W=True, L=False | False | False | True | реальный | crashed |
| W=True, L=False | False | False | False | 0 | clean |
| W=True, L=False | False | False | False | ненулевой | crashed |

Операции обработки Stop/clock/control и final drain выполняются **до** фиксации outcome. Наблюдённый во время drain hard fault также участвует в таблице. Late Stop после уже сформированного closed не переписывает frame; его обрабатывает локальный арбитр C1A. При outcome None нельзя подставить exit0, отправить cleanupTrue или признать slot свободным.

`stopped` означает: guardian принял прекращение compute, direct child уже reaped, и не обнаружено самостоятельного hard fault. Это не утверждение, что именно TERM/KILL стал причиной выхода. Код74, exit0, -TERM/-KILL и иной реальный terminal code не определяют приоритет R; actual code всегда сохраняется. Уже выявленный model/protocol error на стороне S остаётся отдельным фактом для D3/F; guardian не анализирует payload модели.

`clean` недостижим при R/S/H/L, даже если ребёнок успел вернуть result и exit0. Поэтому ошибка сигнала никогда не превращается в successful analysis. При S+R+wait0 вывод pending, при последующем exact wait возможен stopped; это первый подтверждённый исход, не переписывание прежнего crashed.

После выбора kind остальные C1D требования сохраняются: bounded stderr drain, закрытие G slot reference, status encode со **фактическим** code/cleanupTrue, status EOF и exit G. Ошибка release/status delivery не скрывается кодом0; S не подтверждает normal closure по одному прочитанному frame. Этот helper не выполняет SQL, reserve/settle или release S slot.

## 5. Порядок обработки signal race

1. G обрабатывает ordinary Stop и устанавливает R до закрытия gate. При самостоятельной ошибке устанавливает H; общее T просит teardown.
2. Gate закрывается до сигналов, как уже согласовано. Подменять порядок или задерживать отправку «на всякий случай», чтобы тест случайно стал зелёным, не требуется.
3. OwnedChild проверяет NOTE_EXIT. Если exit уже наблюдён — signals_open=False, затем wait, без signal. Если ещё нет — действует прежний TERM/grace/KILL путь.
4. Любая ошибка signal закрывает signals навсегда, записывает S и при необходимости H. **Ни переход True→False для fault, ни retry через другой API/ещё один signal не допускаются.** Допустимы только nonblocking wait polls.
5. wait0 оставляет W=False. Даже успешная отправка KILL не меняет W. Поздний heartbeat не оживляет compute или signals.
6. Exact terminal wait задаёт W/code. Guardian после `_poll` заново читает S/H/L, а не использует snapshot до syscall: signal failure и wait могут случиться **в одном вызове**. Во время последующего stderr drain не превращает aggregate fault в H.
7. После final drain применяется таблица. R=True/S=True/H=False/W=True/L=False → stopped, общий child.fault всё ещё True. При H=True → crashed. При L=True/W=False → закрытие не подтверждено.

Grace≤2s, clock domain, порядок NOTE_EXIT→закрытие signals→wait и запрет PID adoption не меняются. `force=True` не может повторно открыть signals после ошибки. Guardian передаёт force из H/неустранимого native fault, **не из одного S**. Внутренний standalone force callback без ordinary R не создаёт права вернуть stopped; classifier без R выберет crashed при S. Не разрешать новый spawn по одному terminal kind.

## 6. Stop во время bootstrap и другие совпадения

Исправление должно не переносить ту же проблему на раннюю остановку:

- R до spawn: M не создаётся; как раньше, нет выдуманного closed для несуществующего child. Окончательное состояние run решает S/SQL.
- R после spawn, до GO: навсегда запретить GO/armed, прекратить ожидание prepared, закрыть gate и соответствующий reader. Отсутствие prepared/EOF/незавершённый **до отмены ещё валидный** prefix не являются новым H только потому, что startup отменён. Уже обнаруженный malformed token/H сохраняется. После отмены не требуется продолжать парсить остаток ACK для старта, который больше невозможен.
- M завершился до GO **без принятого R**: startup hard fault, как раньше. Нельзя исправить его поздним Stop, если H уже зафиксирован.
- R после valid GO: обычный путь из §5, включая гонку между NOTE_EXIT check и signal.
- R и NOTE_EXIT доступны в одном loop turn: сохраняется приоритет control/Stop; если R принят до фиксации outcome, результат может быть stopped. Это не обещание причинной связи сигнала с exit.
- Known malformed control/clock/kqueue fault до или после Stop: H sticky, итог crashed при W либо unknown без W. Повтор Stop не очищает H.
- Signal error затем stderr flood/ошибка drain: появившийся H меняет ещё не опубликованный итог на crashed. Поэтому недостаточно special-case только перед кодированием status.

Это уточнение касается ожидаемого завершения **отменённого** bootstrap. Оно не допускает GO без prepared, не расширяет C1C/bootstrap protocol и не добавляет новые tokens. Invalid вход до принятия Stop по-прежнему отвергается.

## 7. Границы backend и продукта

- Ни stopped, ни cleanupTrue не равны durable cancelled. Deadline/storage/shutdown/parent death могут дать другие SQL terminal states; C1F читает фактическое состояние с существующими fences.
- D3 выдаёт candidate лишь по clean/exit0/cleanupTrue + valid event EOF + normal G exit + live local budget и отсутствию local Stop/fault. Stopped и crashed никогда не проходят этот gate.
- Stop до C1A commit permit запрещает новую публикацию. Stop после permit не обещает rollback: C1B ordered-lock reconciliation подтверждает реальный исход COMMIT. Успешный SQL result не удаляется ради отмены.
- S удерживает slot до physical completion и SQL reconciliation, затем делает independent acquire probe. При EPERM + wait0, lost ownership, live orphan, unknown COMMIT или missing status новый запуск не разрешается автоматически.
- Threads-only pack, двойной отказ G/S и native Windows/real model/suspend ограничения прежние. Это не новая гарантия OS sandbox или автоматического убийства orphan.

## 8. Что реализовать на Sol6.1 High

Использовать существующий WIP D2; не начинать другую реализацию с нуля. Разрешены исходные восемь D2 файлов и own tests; дополнительно **новая** frozen `tests/acceptance/test_docx_analysis_macos_stop_outcome.py`. Новых runtime modules/API endpoints/DDL/dependencies не нужно.

1. До source changes написать additive acceptance по §9, проверить collection/fixtures, зафиксировать отдельным commit и получить red. Не изменять tests `9afce73` и D1; нынешний failing native Stop остаётся обязательным.
2. `_ownership.py`: private sticky fields + readonly properties S/H/aggregate; выделить только killpg exception scope. Unknown errno→H, expected uncertainty→S; terminal wait не очищает S/fault. Отдельно сохранить lost/close/signals transitions.
3. `_guardian.py`: разнести R/H/T; удалить **обе** агрегации child.fault→hard error. Подключить pure `_closed_kind` в real finalization path, обновлять наблюдения после `_poll` и после drain. Внести отмену незавершённого bootstrap согласно §6, не дать отсутствию GO само по себе перекрыть R. Причины protocol/clock не смешивать с ordinary Stop.
4. Проверить остальные ещё незавершённые части WIP на соответствие D2: descriptor cleanup при частичной подготовке/ошибке spawn, readonly/issued objects, отсутствие raw native errors, canonical CLI/config validation, continuous budget checks перед GO. Уточнение статуса не означает готовность всего D2 по одному исправленному тесту. Если найдётся отдельное архитектурное противоречие — зафиксировать его; обычные implementation fixes входят в текущий цикл.
5. Targeted/own/native + `bash scripts/check.sh`, read-only DB comparison, result/local commit с **всем** проверенным D2 source. Только после этого D2 завершён и можно перейти к D3 на Sol6.1 High.

## 9. Обязательная additive acceptance

Проверки должны доказывать сохранение ограничений, а не только зелёный happy path. Ни sleeps для изменения гонки, ни `assert kind in ('stopped','crashed')` вместо точного исхода.

| Группа | Независимые случаи / ожидание |
|---|---|
| Pure outcome | Все сочетания R/S/H/W/L с terminal0/nonzero; без W/при L/None code нет kind; H всегда crashed при proof; R+S без H stopped; S без R никогда clean; invalid bool/int inputs отклонены |
| Signal errno | EPERM/ESRCH/EINTR на TERM и на final KILL: S/fault True навсегда, H False; EINVAL/EIO/None/unexpected exception → H True. Источник kqueue/wait с тем же errno → H/lost, не signal bucket |
| Same-turn wait | Signal failure + exact wait в одном `_poll` → stopped при R, никакой stale snapshot. Повторная `_poll(force=True)` не отправляет новый signal и не reap второй раз |
| Delayed wait | Signal failure + wait0 + wait0: нет closed, никакого нового signal/GO; поздний terminal wait даёт stopped только с R и без H |
| Hard fault overlap | Stop→protocol/clock/kqueue/stderr fault→wait и hard fault→Stop→wait остаются crashed; invalid wait/ECHILD не выдаёт cleanup proof |
| Before signal | NOTE_EXIT→wait при Stop: ни одного kill; natural exit0 без R/S/H остаётся clean; естественный nonzero без R crashed |
| Early Stop | R после spawn до prepared, на valid prefix и после prepared до GO: no GO/armed и stopped после wait; известный bad token перед R остаётся crashed; no R + early exit до GO crashed |
| Stage/exit code | Код74 без R не означает stopped; код0 с R/S не означает clean; actual code сохраняется, fixture reply не становится ML success |
| Immutability | S/H/aggregate/exited/code/lost readonly; no clearing fault после wait; snapshots/fake DTO не создают owned authority |
| Native integration | Старый обычный Stop по EOF и новый explicit Stop frame; TERM-ignore→KILL; bounded GIL hang; normal fixture; bootstrap cancel; flood+Stop. Проверить status+EOF/G wait и удержание slot; все owned processes reaped |

Нужна детерминированная интеграционная проверка **реального finalization path** G с scripted signal error и scripted wait0→terminal, а не только вызов pure helper. Допустим test-only trusted wrapper/подмена private syscalls в fixture child process; новый production executable/произвольный mode/документный параметр не добавлять. Fake outcome proof не объявлять native OS proof. Дополнительно повторить обычный native Stop20 раз; это smoke устойчивости, не замена детерминированным cut points и не доказательство отсутствия всех гонок. Native permission rejection в среде исполнения сообщать честно, не обходить другим API.

## 10. Передача

**Сейчас можно возвращаться на Sol6.1 High и завершать D03-17C1D2 по этому дополнению.** Затем D3 отдельным циклом. Существующий D2 source/test failure пока остаётся; решение готово к реализации, не реализовано в этом architecture pass. Доказательства и регрессия этого прохода — [отчёт](d03-17c1d2-stop-design-result.md).

Самостоятельный остаток **29–44 цикла**. D2 не вычтен; этот разбор уточняет текущую работу, не добавляет очередную функцию/новый этап и не переоценивает готовность приложения.
