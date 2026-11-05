# D03-17C1F1 — dispatcher и PublicationPort

3 ноября 2026. Следующий implementation cycle на **Sol 6.1 High** после [дизайна C1F](d03-17c1f-design.md). Source/acceptance ещё отсутствуют. Одна задача: сериализовать готовый C1A и предоставить синхронному C1B bounded port, не потеряв permit при гонке ответа. Это внутренний API, не новый HTTP/desktop startup и не scheduler.

## Разрешённые пути

Новый пакет `src/ara/docx_analysis_worker/supervisor/`: `__init__.py`, `dispatcher.py`, `_dispatch_models.py`, `_dispatch_cells.py`, `publication_port.py`. Собственные дополнительные private modules перечислить в implementation preflight **до** freeze. Не менять родительские `__init__.py`; public import из нового пакета/модуля.

Новая frozen acceptance `tests/acceptance/test_docx_analysis_dispatcher.py`; собственные edge tests `tests/docx_documents/test_analysis_dispatcher_*.py`. Документы `docs/d03-17c1f1-{implementation-preflight,result}.md`, обновление статуса C1F/очереди. Без изменения C1A–E, B3/guarded publisher, старых tests, DTO/schema, migrations, зависимостей, main runtime, runner/tasks/progress/AGENTS. Не создавать threads при import/construction; thread dispatch loop — F3, в F1 driver вручную вызывает step.

## Public contract

`create_dispatcher(identity:AttemptIdentity,budget:Budget,*,clock:Callable[[],int]) -> AttemptDispatcher`.

Exact validated/copied C1A identity/budget, callable clock. Создаёт свой единственный AttemptControl, не принимает чужой control. PID-bound, factory-issued, safe repr, no copy/pickle; никакого source/reply/credentials. Initial ControlView берётся у C1A; constructor не вызывает clock/SQL/OS. Все вызовы после fork/на forged object отвергаются. Invalid arguments без mutation: `DispatchError('validation_error')`, foreign/stale handle — `invalid_handle`, wrong step thread — `wrong_owner`, busy — `dispatch_busy`. Fixed messages без исходных exception strings.

| API | Семантика |
|---|---|
| `step() -> DispatchView` | Первый успешный вызов привязывает единственный owner thread; следующие только с него. Обрабатывает конечное число bounded cells, не ждёт появления работы; не запускает внешний callback кроме trusted clock |
| `view() -> DispatchView` | Detached frozen snapshot, без clock/I/O, из любого thread |
| `request_stop(reason='user') -> None` | Closed C1A reason enum, первый reason coalesces; отдельная приоритетная ячейка. Возврат означает принятие запроса, не SQL cancellation/physical exit |
| `post_child_closed() -> None` | Coalesced trusted notification от будущего platform adapter **после** полного physical+EOF+own-I/O proof. Сам не получает/выдумывает proof; нет такого public JSON command |
| `post_lease_ack(*,started_ns,received_ns,remaining_lease_ns) -> LeaseTicket` | Один слот exact integer data; если предыдущий ticket ещё не забран — busy без mutation. Возврат означает enqueue, не принятую lease |
| `take_lease_result(ticket) -> LeaseDecision \| None` | Pending→None; resolved→выдаёт и освобождает единственный слот. Foreign/повторно взятый ticket — invalid_handle. Ticket issued/PID-bound/no copy/pickle |
| `publication_port() -> PublicationPort` | Всегда тот же выданный subclass frozen ABC `ara.docx_analysis_runs.guarded_port.PublicationPort` |

`DispatchView`: `control:ControlView`, `stop_pending:bool`, `lease_pending:bool`, `child_pending:bool`, `publication_pending:bool`, `fault:str|None` (`clock` либо `internal`). Нет mutable references/cell/token/thread/PID. `LeaseDecision`: `accepted:bool`, `lease_ns:int`, `control:ControlView`; accepted означает **новый bound действительно принят C1A**, не ACK G. Ticket/permit не включать в view/errors/log.

## step и clock

Порядок каждого step: latched Stop и fresh tick; lease receipt; child_closed; publication cell. Перед **каждым** переходом C1A свежий clock sample. Короткая синхронизация request_stop и reserve делает выбор победителя однозначным: если Stop принят до reserve, drain его непосредственно перед reserve. Статус `publication_pending` сам не даёт permit. Два concurrent step запрещены; не менять owner при смерти потока и не продолжать control в другом thread.

Clock exact int0..2**63-1, bool/float/NaN/exception — clock fault. На fault latch Stop('clock') с последним валидным C1A time; новые reserve/lease запрещены. Это относится и к clock fault внутри caller port: caller ставит ту же coalesced Stop ячейку, но не вызывает C1A из чужого thread. Backwards sample dispatcher передаёт C1A tick, который отзывает право продолжения, а не clamp с продлением; caller при регрессии относительно начала своего ожидания abandons и сообщает clock fault. Clock callback считается trusted bounded operation: F1 не обещает остановить зависший callback и не создаёт replacement thread; независимый guardian остаётся защитой F3. После clock fault known settlement committed всё равно доставляется с last valid sample. Не превращать committed в cancelled.

Lease: validate s≤r, duration1..15s, checked sum; при step r≤fresh_now, started не в будущем. Новый guarded bound=min(D,s+duration-guard). Если bound≤текущей L, phase не open, Stop pending либо свежий now≥старой L/D — rejected, без продления. Иначе `C1A.acknowledge_lease(started_ns=s,received_ns=fresh_now,remaining_lease_ns=duration)`. Original r остаётся проверкой получения, но не временем позднего перехода. Затем Decision по фактическому view; guard второй раз не вычитать. Просроченный, но ранее поступивший receipt не оживляет attempt. Не принимать второй heartbeat, пока первый decision не consumed.

## Port reserve: недоставленный permit

`port.view()` возвращает exact frozen ControlView того же attempt (последний snapshot), без clock/transition. `reserve()` и `settle()` нельзя вызывать из owner thread: это self-wait, safe dispatch_busy. Один publisher caller за раз; конкурентный вызов не создаёт очередь.

`reserve()->CommitPermit|None`: одна cell и максимум50ms continuous-clock caller budget. Состояния cell `requested→offered→taken` либо `abandoned`; внутренние, не новый C1A status. Dispatcher единственный вызывает C1A.reserve. Offered token остаётся приватным до caller acceptance. Caller, проснувшись, под коротким cell lock повторно проверяет fresh clock/cutoff; только своевременный accept переводит taken и возвращает **тот же** opaque C1A token. Очередь/request/offer/Condition.notify не равны принятию. Если C1A отказал, None. До перехода taken timeout/clock fault abandon, None, token не выдаётся позднее.

Сами Condition waits дополнительно ограничены общим50ms бюджетом `time.monotonic_ns()`, чтобы constant fake/broken continuous clock или spurious wake не создавали бесконечное ожидание. Это только более ранний выход из ожидания: этот вспомогательный clock никогда не выдаёт permit, не вычисляет D/L и не заменяет continuous check после сна. Такое же ограничение действует для settle. При исчерпании любого wait budget — соответствующий timeout, без «ещё50ms» на каждый wake.

Abandoned requested не вызывает reserve. Если token уже offered, dispatcher при следующем step ровно один раз `settle(token,rolled_back)` прежде следующей reserve: отсутствие доставки caller доказывает отсутствие SQL с ним. Stop в этой гонке оставляет stopped; без Stop возможен новый permit по C1A. Пока rollback не обработан, cell busy. После taken request cell освобождается для settlement; token остаётся в C1A и у caller, новая reserve по-прежнему запрещена состоянием C1A. **После taken** любой timeout/смерть caller/Stop не дают права самовольно rollback: token уже мог попасть в C1B/COMMIT. Только явный SQL outcome от trusted publisher/reconciliation; при его отсутствии pending/unknown сохраняются.

Для read/offer/take/abandon используется один короткий cell lock. При caller take fresh clock читается **после** получения lock и непосредственно перед проверкой cutoff; нельзя использовать sample, снятый до ожидания lock. Это единственное разрешённое обращение к trusted bounded clock в этой критической секции; SQL/native waits/другие callbacks запрещены. Test clock не должен искусственно ждать barrier, удерживая cell lock. 50ms — policy cutoff, не hard OS wall-time guarantee: обнаруженное позднее пробуждение не выдаёт token. Strong reference offered/taken не теряется от GC/timeout. Если сам trusted clock завис, новый dispatcher/permit не создаётся, попытка остаётся удержанной; F3 guardian имеет независимый cutoff.

## Port settle: durable outcome не отменяется тайм-аутом

`settle(permit,*,outcome)->ControlView`, exact C1A token и closed outcome enum. Одно non-cancellable delivery cell; bound ожидания50ms. Dispatcher вызывает C1A.settle с fresh clock (или last valid при clock fault), сохраняет ответ до получения caller. Если caller timeout — fixed `DocumentError` через прежний `publication_in_progress`; cell/token/outcome остаются. Это не rolled_back и не разрешение следующей reserve.

Повтор той же операции присоединяется к pending/готовому ответу без нового payload/cell. Конкурентный другой outcome не перезаписывает предыдущий и получает busy; сначала доставить pending, затем следующий разрешённый C1A переход. В частности fallback `unknown` из C1B при потерянном ACK committed не затирает committed. После доставки replay/conflicting outcome проверяет сам C1A: same/unknown replay допустимы по frozen правилам, несовместимый resolved outcome отвергается. Неверный/старый/чужой permit не сбрасывает действительный token.

Новый reserve запрещён, пока settlement delivery не согласована или предыдущий token committing/unknown. После known rolled_back C1A может выдавать новый token только если не Stop/expired; старый становится invalid по прежним правилам. F1 не решает SQL outcome сам, не вызывает C1B.complete/reconcile, не хранит reply и не освобождает OS slot.

## Boundedness и приёмка до source

В памяти один control, один port, по одному Stop/child/lease/publication slot; не список событий/history или Futures на каждый tick. Completed publication receipt заменяется только после согласованного consumption; не накапливать token history. Строки/числа ограничены; replay coalesces; exception не содержит пользовательского текста. F1 создаёт **ноль worker threads/connections/processes**. Test harness имеет фиксированное число потоков и explicit joins.

Новая acceptance должна упасть red до появления source; freeze contract+tests отдельным commit. Проверки через fake continuous clock и barriers, не десятки sleep races:

1. Constructor/import inert; точные type/range/enum ошибки, defensive copies, detached view, repr/pickle/fork/forged handle, owner thread affinity и concurrent step.
2. Stop flood/lease flood/publication busy не растят cells; Stop проходит при pending lease/reserve/settle. Тысячи metadata/tick calls не создают threads/history.
3. Fresh clock для каждого transition; задержка между ACK и step через старую L, sleep past D, backwards/invalid/raising clock. Ни один путь не продлевает D; committed переживает fault.
4. Timely heartbeat увеличивает L ровно по исходному s+duration-guard, поздний receipt/малый bound/не-open phase отвергается. Queue acceptance отдельно от LeaseDecision, foreign/consumed ticket и второй receipt без consume.
5. Нет permit до child_closed; полный physical proof моделируется trusted notification, view/candidate flag не заменяет её. Stop-before-reserve даёт None; Stop-after-reserve позволяет settle committed, rolled_back после Stop не открывает новое право.
6. Reserve timeout до обработки; offered до caller timeout; late wake; clock fault caller; concurrent take/abandon; offered rollback обработан один раз; **taken token никогда не откатывается автоматически**. Следующий grant невозможен, пока abandon cleanup pending.
7. Settle timeout до step и после выполнения до ACK; same retry; fallback unknown при pending committed; conflicting/foreign/old token. Lost ACK не теряет outcome, не создаёт новый permit и не регрессирует succeeded.
8. C1B-compatible port identity и fixed DocumentError busy, без изменения DirectPublicationPort. Проверить настоящую цепь C1A reserve→unknown→rolled_back→new token и reserve→Stop→committed через новый adapter; SQL composition остаётся F3.
9. Owner thread не вызывает свой blocking port; bounded pending при недоступном dispatcher, без replacement threads. Проверки ожидания50ms используют управляемый clock и deterministic wake/barriers; честно отделить policy cutoff от hard scheduling guarantee.

Implementation preflight фиксирует exact API/tests и baseline до freeze; ошибка подготовки нового frozen test требует узкого согласования согласно правилам проекта, а не ослабления assertion. После source targeted + `bash scripts/check.sh`, code/test hashes старых компонентов и read-only main DB snapshot. Main V8 не мигрировать. Result сообщает actual tests/skips, ограничения и локальный commit.

После зелёного F1 на том же Sol6.1 High переходить к **F2 preparation** по дизайну: exact V11 DDL/ORM, scoped SQL receipts/ledger services, необходимые narrow V10-test pins, новая независимая приёмка. Если возникнет несовместимость, зафиксировать её до правки frozen файлов. Производственный supervisor, Windows boot proof и модель не являются выполненным результатом F1.
