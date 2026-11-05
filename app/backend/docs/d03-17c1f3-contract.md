# D03-17C1F3 — композиция supervisor

**Дополнение от 3 ноября:** [continuous timeout / V12](d03-17c1f3-timeout-addendum.md) уточняет только схему, startup version и подготовку исторических migration tests. Его точные разрешённые пути имеют приоритет над запретом schema changes ниже; остальные требования сохраняются. По последней команде Никиты разработка продолжается на Astra без остановки для переключения модели.

3 ноября 2026, Astra 6 High. Уточнение [C1F](d03-17c1f-design.md) по [F3 preflight](d03-17c1f3-preflight.md), после F1 `72fb8f8` и F2 `3fc77f2`. Относится к F06–F08/F12 [текущего продукта](current-product-scope.md). Это один цикл реализации на **Sol 6.1 High**, с тремя последовательными группами проверок, без новых продуктовых функций. В этом design pass source/тесты/схема не меняются.

**Решение конфликта:** локальная остановка запрещает новую публикацию сразу. Отдельное, выданное живым supervisor полномочие разрешает сохранить её причину в SQL только после разрешения прежних SQL-записей и publication permit. Оно не доказывает физическое завершение процесса и не очищает launch ledger. Любой уже записанный terminal outcome, включая success, неизменяем. Pending COMMIT сначала проходит прежний C1B reconciliation.

Этот документ уточняет только композицию F3; замороженные C1A–E/F1/F2 и их приёмка не переписываются. Матрица [F3 acceptance](d03-17c1f3-acceptance.md) нормативна вместе с этим контрактом. Production bootstrap, реальная модель, автоматический выход из armed quarantine, UI/HTTP и миграция рабочей БД не входят.

## 1. Разрешённые пути и порядок цикла

Только новые файлы в `src/ara/docx_analysis_worker/supervisor/`:

- `runtime.py`, `_runtime_models.py`, `_registry.py`, `_jobs.py`, `_coordinator.py`, `_admission.py`, `_attempt.py`, `_recovery.py` — explicit API, ограниченное состояние и scheduler;
- `_exit_authority.py`, `_terminal.py`, `_queries.py`, `_publication.py` — локальные полномочия, SQL terminal bridge, read barriers и обёртка существующего PublicationPort;
- `platform.py`, `_macos_adapter.py`, `_windows_adapter.py` — доверенные порты и адаптеры готовых native drivers.

Разделять функции между этими файлами допустимо, добавлять другие source paths — только после конкретного обоснования границ. `supervisor/__init__.py` и все существующие source остаются неизменны; новый API импортируется из `supervisor.runtime`. Никаких новых migrations/models/DDL/endpoints/dependencies, изменений runner/tasks/progress/check/conftest и прежних acceptance. Main остаётся V8; новая композиция работает только с явно подготовленной **одноразовой V11** в приёмке.

Новые проверки: `tests/acceptance/test_docx_analysis_supervisor_runtime.py`, `tests/acceptance/test_docx_analysis_supervisor_recovery.py`, `tests/acceptance/test_docx_analysis_supervisor_native.py`; собственные вспомогательные/edge tests — `tests/docx_documents/test_analysis_supervisor_runtime_*.py`. Synthetic test doubles располагаются в новых тестовых файлах, не подменяют production adapters. Эти contract/acceptance/result/preflight docs и статусы C1F/development queue — parent preparation/reporting, не изменения критериев внутри implementation.

Перед source: подготовить independent acceptance по всей матрице, проверить сам harness и зафиксировать freeze; показать red из-за отсутствия F3. Затем последовательно: (1) jobs/полномочия/SQL bridge/port, (2) portable coordinator с настоящим PostgreSQL, (3) native adapters и доступные platform gates. Это checkpoints одного F3, не три новых ID и не разрешение ослабить поздние проверки. В конце targeted/full, сохранность baseline/main, result, локальный commit. Не объявлять весь F3 готовым по первой группе.

## 2. API и граница доверия

`create_fixture_supervisor(*, settings: DatabaseSettings, user_id: UUID, project_id: UUID, installation_id: UUID, root: Path, execution: ExecutionSpec) -> Supervisor` — инертная фабрика. Точные immutable копии настроек/UUID/spec; `execution_kind` только `fixture`. Root абсолютный private root прежнего native owner, без создания произвольной альтернативы при ошибке. Настройки явно передаёт bootstrap; никакого чтения секретов, I/O, threads, connection или OS calls при import/construction. Native adapter выбирается только по поддерживаемой ОС. Unsupported host → safe error, не portable fallback. Limits старых codec/driver фиксированы, не увеличиваются.

При явном start F2 создаёт три отдельных engine; из них — локальные DocumentRuntime с фиксированными user/project. Общий engine приложения не меняется. Installation ID не является пользовательской настройкой обхода: он обязан совпасть с уже provisioned ledger. Фабрика **не** вызывает `provision_new_database`. Задать готовый root/DB может только доверенный bootstrap; HTTP/JS не получают ни эту фабрику, ни settings, ни PlatformPort. Public fixture API не подключается к обычному приложению этим циклом.

`Supervisor` — issued, PID-bound, uncopyable/unpickleable, safe repr. Методы:

| Метод | Результат и смысл |
|---|---|
| `start()` | `SupervisorView`; идемпотентно начинает startup один раз, возвращает `starting` без ожидания БД/native; не перезапускает умерший thread |
| `view()` | Detached metadata snapshot; не делает I/O, не вызывает driver/callback и не продвигает scheduler |
| `admit_saved(*, client_request_id, command: SavedCheckCommand, target_provider)` | Выданный `RunTicket`; только после ready, для server-owned scope; provider выполняется в admission lane |
| `retry(*, client_request_id, command: RetryCheckCommand)` | Тот же механизм билета; новый явный run/key, source из прежнего B3 retry; не resume старой попытки |
| `ticket_view(ticket)` | `RunTicketView`; только собственный issued ticket, без SQL/payload |
| `stop(ticket)` | `RunTicketView` с принятым stop intent; идемпотентно, без ожидания БД/codec/native; это **не ACK SQL cancelled** |
| `shutdown(*, timeout=5.0)` | `bool`: True только после всех own jobs/threads/resources/owner/pools; False означает retained pending, не teardown proof |

Timeout — finite number 0..5s, один общий wait budget, не 5s на каждый thread. Auxiliary monotonic ограничивает ожидание вызывающего потока, никогда не продлевает continuous deadline. Повтор shutdown продолжает ту же очистку, не создаёт новый runtime. Из coordinator/lane thread shutdown не блокирует/join себя.

`SupervisorView`: `phase` (`new|starting|ready|stopping|blocked|closed`), `fixture=True`, `error_code|None`, `queued_count`, `active_run_id|None`, `pending_lanes: tuple[str,...]`, `recovery_required: bool`. `RunTicketView`: `phase` (`admitting|queued|active|settling|finished|not_admitted`), `run_id|None`, `document_id`, `stop_requested`, `stop_reason|None`, `sql_state: RunState|None`, `error_code|None`. SQL state — последний **подтверждённый** receipt; локальный Stop/истёкший срок показывается отдельно, не выдаётся за durable terminal. stop_requested включает немедленный intent; stop_reason остаётся None до сериализованной обработки и затем отражает её first reason. `finished` означает согласованный SQL terminal, но глобальная готовность следующего запуска определяется SupervisorView/ledger. Тексты, command/source/reply bytes, paths, handles, SQL, settings и exception strings не входят в snapshots/errors/repr/log.

Новый `SupervisorError.code`: `validation_error|invalid_handle|not_ready|busy|queue_full|storage_unavailable|storage_error|clock_error|runtime_unavailable|recovery_required|shutdown_pending|internal_error`; safe fixed message. Existing DocumentError коды из B3 сохраняются в отрицательном результате admission; никаких новых Run statuses/error codes. Выданные билеты проверяются по object identity + PID + конкретному Supervisor, не только UUID.

Для переносимой приёмки отдельный **внутренний** constructor принимает доверенный `PlatformPort` и clock, использует тот же coordinator/SQL/GuardedPublisher. Не переключатель production API и не bool `cleanup_proven`. Port может предоставлять только test fixture/доверенный native adapter; arbitrary caller DTO не становится authority. Clock/type/value failures закрывают admission и новые grants.

## 3. Threads, ячейки и время

Один coordinator thread — единственный owner F1 `step()`. Пять постоянных lanes, по одному thread, одному job (включая submitted ещё не начатый) и одному невычитанному result cell; новая работа только после потребления результата прежней. Никакой очереди future jobs внутри executor и overflow threads. Результат содержит job generation + safe outcome; late receipt не относится к другому attempt. До Thread.start lane зарегистрирован сильной ссылкой; ошибка start без подтверждения отсутствия выполнения — unknown, без replacement. Результат публикуется после возврата callback и завершения его finally/session cleanup; необработанное BaseException становится retained fault, а не потерей busy.

| Lane | Собственность |
|---|---|
| admission | B3 start/retry, target/source preparation, scoped lookup при неизвестном enqueue; engine admission |
| SQL control | startup probes/reaper, exact claim, arm, heartbeat, terminal bridge, ledger transitions; engine control |
| publication | один GuardedPublisher и все его complete/reconcile/settle-ACK retries, restore success; engine publication |
| platform lifecycle | acquire owner/slot, factory, observe/candidate, close, release/probe slot, close owner |
| platform control | renew/Stop существующего driver, без data parsing/process waits |

На SQL lane одна сессия/операция в момент времени, максимум три соединения F2. Тайм-аут 5s ожидания job — только stalled/pending: lane и connection не освобождаются, thread не заменяется, вызов не считается rollback. Первый storage fault закрывает admission/claim и останавливает текущий compute; уже принятые queued intents также прекращаются, не стартуют в сломанном runtime. Разрешение прежних исходов продолжается. После полного согласования/clean можно восстановить ready тем же S; никаких новых anchors для старых intents.

SQL control отдаёт приоритет активному lease/Stop/unknown outcome; reaper не монополизирует lane. Один ограниченный reap (`limit=32`) по расписанию около1s, heartbeat около3s, metadata native observation около10ms при active. При busy — coalesced due flags, не backlog jobs. Повторные reconciliation после завершившейся ошибки используют 0.25/0.5/1/2s bounded backoff (затем2s), один job; отсутствие progress не создаёт новые threads. Нельзя бесконечно spin-loop повторять operation, надеясь расширить lease.

После fault continuous clock вспомогательный monotonic допустим для scheduling повторов cleanup/reconciliation и ограничения caller wait. Он не вычисляет D/L, не даёт candidate/grant/renewal и не «чинит» first Stop reason. Поэтому сломанный clock не мешает доставить уже известный COMMIT outcome и закончить доступную очистку.

**Wake для F1:** обёртка port и caller intake сигналят coordinator Event. Пока существует active dispatcher или публикация/settlement, coordinator wait **не более5ms**; в idle — не более250ms с учётом ближайшего queued deadline. Сигнал до появления F1 cell может быть ранним: 5ms servicing закрывает lost-wakeup окно без доступа к приватной F1 condition. В каждой итерации bounded metadata work и fresh `step()`, сначала Stop/cutoff. 50ms F1 остаётся прежним, не увеличивается. Это scheduling policy, не обещание real-time: при OS stall port safely times out, offered/taken протокол сохраняется. Caller UI polling для работы не нужен.

Во время coordinator metadata mutex: только фиксированные поля/ячейки, максимум17 entries. Ни callbacks, SQL, codec, driver methods, wait/join, platform factory, disposal; clock sample тоже вне общего mutex. F1 владеет собственным коротким lock. `stop(ticket)` перед возвратом доводит intent до `dispatcher.request_stop` вне общего mutex; момент принятия Stop активной попыткой — F1 intake lock. Окончание вызова stop до reserve запрещает новый grant. При одновременных вызовах результат определяется F1 linearization, а не порядком кликов/UUID.

Исходный `e` native continuous clock берётся до admission job; `D_enqueue=e+300_000_000_000-50_000_000`, checked integer arithmetic. Перед claim job фиксируется `s`, после действительного ACK `r`; `make_budget` использует целочисленные SQL durations, затем D=min(его D,D_enqueue), L=min(его L,D). Guard ровно один раз на каждом независимом исходном bound, не ещё раз после min. Повтор receipt не обновляет e/s. Clock regression/failure — Stop clock с последним valid sample, не новый срок. Нет перевода времени через клиентский wall clock.

Heartbeat ACK: `s_h` до SQL, `r_h` после; duration=lease_expires_at−heartbeat_at **из того же receipt**, native clock fresh при F1 processing. Один LeaseTicket до consumption. Native renew получает только F1-accepted bound; принятие SQL heartbeat само по себе не продлевает G. Отдельно хранится последний доставленный native L. False/busy позволяет только тот же bound, после завершения прежнего job и пока **старый** native L жив; expiry старого L → Stop lease. Во время factory до handle нет renew — G ограничен начальным L. После natural physical proof и захваченного candidate renew G больше не нужен; SQL/F1 lease для валидации продолжается до D.

## 4. Admission, очередь и неизвестные ACK

Сильный registry хранит максимум16 ожидающих intents **включая in-flight admission** и одну active generation (claim pending также active). Тяжёлый target/source — максимум одного admission job и одной active попытки; queued entries metadata-only. Если ещё нет active, общий максимум16, а не17 queued. Тот же зарегистрированный `(document_id,key)` и exact encoded command возвращает тот же ticket/anchor; несовпадение — прежний idempotency_conflict. На busy admission новый key получает busy, provider не вызывается. Повтор уже зарегистрированного key не занимает второй lane/entry.

B3 start/retry используются без изменения. Target callback не идёт в coordinator; его зависание оставляет admission busy, Stop/shutdown продолжаются независимо. Stop или D во время callback не могут отменить уже вошедший B3 job: поздний durable enqueue будет разрешён по тому же ticket и немедленно завершён без claim/inference. Не удалять его из registry по локальному timeout.

После B3 ACK entry сохраняет source metadata и accepted command SHA, освобождает source payload/provider reference. FIFO по accepted registry order; новый claim только registered entry с живым D, clean ledger и свободными ресурсами. Не использовать `claim_next`. SQL queue limit16 остаётся обязательным независимо от RAM.

**Enqueue ACK-loss:** пока original job не закончился — только ожидание. После завершившейся ошибки один `_storage.lookup` с прежними command/key/encoded в admission lane. Его project/shared document lock — barrier против committing enqueue, которое держало document write lock. Условие доказательства: прежний helper использует обычную explicit transaction, COMMIT посылается только после scope/write lock; нет фонового продолжения helper/pipelined будущей записи после job. Если прежний COMMIT ещё может завершиться, barrier ждёт lock; иначе видит committed row либо absence. Ошибка/timeout lookup — unknown, не negative receipt. Никакого повторного `start_saved` для разрешения unknown.

Found row регистрируется с **исходным** e/D и Stop; terminal replay не запускается, не получает новый budget. Confirmed absent → `not_admitted`, callback/insert автоматически не повторяются, queue reservation освобождается. Чужая scope/удалённый document/idempotency mismatch — safe blocked/error, не утверждение «ничего не сохранилось». Незарегистрированный active replay в живом S — invariant violation/recovery_required, а не повод присвоить ему новый e. Startup обязан сначала устранить старую очередь.

Завершённый ticket хранит только detached outcome у caller; S удаляет его из active map после cleanup/разрешения admission и не держит бесконечный cache завершённых keys. Повтор принятого key после eviction проверяется durable B3 lookup и возвращает terminal outcome. Для **никогда не принятого** key нет вечной SQL tombstone: пока ticket жив, он показывает прежний negative outcome; новый submit после его завершения — новый admission intent, не восстановление неизвестного. UI retry должен выдавать новый key. Это не разрешает переякорить unresolved/accepted run.

Перед exact claim lifecycle lane получает slot. S заранее назначает attempt/worker/launch UUID; до и после ACK проверяет original D. Unknown claim после завершившегося job разрешается новой read barrier под project→document→run→attempt locks: matching running можно восстановить через F2 `claim_exact` read-replay; queued означает отсутствие claim, **не** команду повторить claim. Terminal сохраняется. Из-за storage Stop ни одна из этих recovery веток не запускает inference. Перед create отдельный `arm_launch` ACK; неизвестный arm читается `read_fence` после окончания original job. Armed matching не является разрешением повторного create; при уже принятом Stop это ветка no-create drain.

## 5. Publication port: wake и точный повтор settlement

Новый внутренний `WakePublicationPort(PublicationPort)` делегирует F1 port, не DirectPublicationPort. `view/reserve/settle` принадлежат одному publication lane и одному GuardedPublisher. `reserve` сигналит wake перед delegate; выдача/take/abandon token остаются исключительно F1. Обёртка не конструирует permits и не расширяет wait50ms.

Перед `settle(token,outcome)` обёртка сохраняет **одну** точную пару token/outcome, пока delegate не вернул ACK. При timeout/error она удерживает пару. Перед новой отличающейся settlement обёртка сначала доставляет/получает ACK прежней пары; если не вышло, новый outcome не делегируется. Дополнительный `flush_settlement()` повторяет ровно эту пару, в publication lane и без SQL, перед следующим C1B reconcile/complete. Это необходимо, например, когда C1B уже меняет unknown на committed, но F1 ещё держит completed unknown cell. Не очищать F1 private cell, не терять ранее отправленный committed/rolled_back/terminal outcome. Если повтор старого outcome завершился, последующий другой outcome допускает или отвергает сам frozen C1A.

Один retained GuardedPublisher создаётся на exact claim/port, не пересоздаётся при timeout/исключении. Complete использует exact candidate bytes. Pending/unknown COMMIT → flush → **тот же** publisher.reconcile, пока settlement действительно unresolved. Пока original publication job не вернулся, нельзя запускать второй SQL job для выяснения его исхода, finalizer или новый complete. После результата consume cell; следующая операция разрешена лишь тогда, когда прежний вызов фактически окончен. Любая ошибочная/неизвестная публикация включает Stop storage и закрывает новые compute grants.

**Resolved settlement с потерянным ACK — отдельная ветка.** Обёртка держит ещё одну metadata запись последнего подтверждённого token/outcome (`committed|rolled_back|terminal`), максимум один token на попытку. После flush, когда этот resolved outcome подтверждён F1 и publication job окончен, S может окончательно **запретить дальнейшие вызовы retained publisher** и перейти к read-only ordered SQL barrier/restore. Не менять его private `_pending`, не создавать замену. Это не новый settlement: C1B уже установил SQL факт до запроса settle, F1 теперь подтвердил ровно этот факт.

Так закрывается конкретная гонка: C1B доказал rollback → F1 выполнил rolled_back, ACK потерян → reaper успел поставить terminal → повтор C1B мог бы послать terminal для уже resolved rolled_back token и получить conflicting_outcome. F3 не посылает этот конфликт: flush получает прежний ACK, seal publisher, read barrier видит новый SQL terminal как **отдельный факт**. При committed helper обязан source-backed restore и exact retained reply comparison; при rolled_back helper подтверждает отсутствие success/result перед terminal bridge. Неожиданный success при уже доказанном rolled_back — corruption/recovery_required, не смена token outcome. При unknown никакой такой shortcut нет: требуется C1B reconcile. При resolved terminal сохраняется прежний SQL terminal, success не принимается как допустимое новое состояние.

Если `complete` вернул rejected/running без принятого token (например, недоставленный reserve), сначала F1 обслуживает abandon, затем можно повторить **тот же** complete с теми же bytes/объектом, только при live open C1A и отсутствии Stop, с bounded backoff. Если job бросил исключение, применяется Stop/reconcile, а не optimistic повтор complete. `phase=committing|unknown` никогда не является разрешением terminal bridge. `succeeded` выдаётся только после source-backed C1B reconciliation и COMMIT receipt; `succeeded` в RAM без durable/source verification не становится UI результатом.

Когда C1B reconcile после Stop записывает `cancel_requested`, это его техническое fencing, **не обязательно пользовательская причина отмены**. F3 exit authority сохраняет исходную причину: local deadline может завершить ещё nonterminal `cancel_requested` как timed_out, storage/clock — failed/interrupted. Уже terminal `cancelled`/`failed`/`timed_out` не перекрашиваются.

## 6. Полномочие local Stop → SQL terminal

### 6.1. Кто его выдаёт

`ExitAuthority` — private issued identity object из `_exit_authority.py`, не dataclass с полями, не constructor по UUID/reason, не сериализуемый DTO. Private issuer принадлежит одному живому coordinator/generation, проверяет PID/object identity и держит server-owned bindings в своей таблице (максимум один на каждый из17 entries). SQL worker получает read-only решение через проверку issued object. Нет API `timeout(run_id, reason)` и bool `local_deadline_elapsed=True`. Это защита от случайной подмены полномочий внутри trusted Python bootstrap, не sandbox против произвольного Python-кода/администратора.

Для issuance нужны все условия:

1. Собственный зарегистрированный ticket, прежний e/D и **первый** Stop reason. Для active с dispatcher — fresh обработанный F1 ControlView; для queued/admitting/claim-pending без dispatcher — native continuous sample coordinator и сохранённый stop intent. В последнем случае сначала clock validity/expiry D, затем user/storage/shutdown intent; first reason не определяется порядком caller timestamps. Deadline reason возможен лишь при наблюдении `now >= effective D`; дефект/регрессия clock даёт clock, не искусственный deadline. Причина не улучшается задним числом при последующих ticks. Если Stop обработан до создания dispatcher, поздний claim ACK не создаёт новый C1A для переопределения причины: no-publication доказано отсутствием publisher/dispatcher, сохраняется прежнее локальное решение.
2. Admission исход известен. Exact run/accepted scope/key/command SHA/source pins привязаны к entry; pending claim/arm разрешены до известного no-claim/claim/ledger состояния. Ни один старый admission/claim/arm job ещё не может изменить эту identity.
3. Для entry **закрыт доступ к новым complete/claim/arm/heartbeat**. Publication job завершён, retained settlement ACK вычитан; fresh F1 step применил Stop/abandon. Control не committing/unknown, port cell пуста. Ранее принятый permit либо вообще отсутствует, либо C1B согласованно settled rolled_back/terminal/committed. Committed/succeeded требует restore и **не выдаёт** authority для перезаписи. Наличие SQL connection timeout не заменяет эти доказательства.
4. Issuer фиксирует generation seal: дальнейшая публикация/heartbeat этой entry невозможна; возможны только exact terminal retry/read и native Stop/cleanup. Выданный authority содержит внутренние immutable pins, owner installation/epoch, optional exact attempt identity/claim metadata и first reason/effective bounds. Snapshot от UI не является его источником.

Authority не требует physical exit: durable статус может стать timed_out, пока OS cleanup pending. Оно не даёт record_drained/clear/slot release. Неизвестный create сохраняет armed даже после terminal SQL. Pending compute может существовать, но больше не получает publication grant.

### 6.2. Транзакция и приоритет

Private `_terminal.apply_exit(engine, authority) -> RunState` вызывается только SQL control lane. При каждом повторе проверяет живого issuer/seal, immutable pins, owner epoch. Замок project→document→run→attempt, затем ledger; использовать frozen ordered helpers. Для trusted cleanup допустим unscoped lock helper, но принятые project/owner в run должны **точно совпасть** с authority. Изменение текущего владельца документа затем обрабатывается как прежний ownership_changed; public caller не передаёт scope/authority. Проверить record fields, command SHA, accepted source metadata и exact optional attempt; несовпадение/удалённая запись → recovery_required без случайной записи.

Для ещё queued entry ledger может быть clean, armed или drained **другой** active entry того же owner; это не чужой launch proof. No-claim authority требует run.attempt_id=None и queued/terminal. Claimed authority требует exact attempt/worker/fence и прежние source pins; ledger clean допустим только в подтверждённой unarmed/no-create ветке этого S, иначе armed/drained с полным matching LaunchBinding. Ни один writer не получает право очищать ledger по terminal authority.

После проверки bindings:

| Условие под locks | Действие |
|---|---|
| Run уже terminal | Вернуть существующий outcome без UPDATE; success отдельно source-backed restore, результат не удалять |
| Текущий project/owner не совпал с accepted scope | `failed / ownership_changed` |
| SQL `now >= deadline_at` | `timed_out / deadline_exceeded` (прежний серверный предел остаётся) |
| Выданная причина `deadline` | `timed_out / deadline_exceeded`, даже если SQL wall deadline/lease ещё живы |
| Причина `user` | `cancelled / cancelled` |
| Причина lease, clock, storage или shutdown | `failed / interrupted` |
| Причина child или protocol | `failed / adapter_error`; отдельно уже подтверждённый C1B invalid_result не меняется |

Для nonterminal применять существующий `life.terminal` и прежние ограничения схемы: terminal stage, fence1 без attempt/fence2 с attempt, lease NULL, finished/updated=max(SQL now,created_at); cancel_requested_at для cancelled по прежнему правилу. **Не** вызывать `life.expire` перед выбранной локальной причиной так, чтобы wall lease подменил подтверждённый local deadline. No claimed lease/deadline/source timestamps переписывания. Первичность уже существующего terminal обязательна даже если его ранее поставили C1B/reaper по SQL lease: F3 не обещает задним числом заменить failed/interrupted на timed_out. В этой ветке сохраняется также локальная причина в ticket, без ложного durable ACK.

COMMIT ACK-loss: тот же authority остаётся retained, новые jobs закрыты. После фактического окончания original job повтор `apply_exit` под теми же locks либо возвращает уже terminal, либо атомарно заканчивает прежнюю nonterminal запись. Не новый token/reason/generation. Side effect разрешён только этой одноразовой entry; authority от другой попытки/S/fork, copied/reconstructed и issued до публикационного barrier запрещены. После confirmed receipt authority отзывается, повтор UI stop читает detached state.

### 6.3. Что даёт такая граница

До reserve Stop блокирует публикацию, затем bridge сохраняет точный local timeout без ожидания SQL wall deadline. После take Stop не решает, был ли COMMIT: сначала C1B barrier/restore/settle, success остаётся success, rollback допускает bridge. При потерянном COMMIT ACK и зависшем job запись terminal не стартует. При недоступной БД немедленно останавливаются RAM/native grants, UI видит pending settlement; confirmed timed_out/cancelled/success не выдумывается. Конфликт F3 preflight разрешён **добавлением** этого узкого trusted bridge, не изменением старых C1A/B/F2.

## 7. Native adapter и владение запуском

`PlatformPort` — внутренний trusted protocol: `clock()`, `acquire_owner(root)`, `reserve_slot(owner)`, `launch(slot, identity, budget, *, request, execution_spec)`, `observe(attempt)`, `renew(attempt,bound)`, `stop(attempt,reason)`, `close_attempt(attempt)`, `release_slot(owner,slot)`, `close_owner(owner)`. Adapters вызывают только прежние native API и возвращают private issued handles/metadata. Нет `adopt_pid`, raw HANDLE/FD в coordinator, `force_close`, `abandon`, reset-by-bool или публичного injection произвольной factory. Mac/Windows lazy imports, на другой ОС native module не импортируется для side effects.

Return shapes в `platform.py`: clock — int ns; acquire/reserve/launch — opaque own wrappers; renew/release — exact bool; stop/close_owner — None при завершении; close_attempt — `CloseObservation(closed: bool, physical_confirmed: bool)`; observe — frozen `NativeObservation(stage: str|None, error_code: str|None, physical_confirmed: bool, candidate: bytes|None, captured_ns: int|None)`, candidate field repr=False. Capture time присутствует только вместе с bytes; physical_confirmed означает именно прежний native proof, не view.phase/close flag по отдельности. Wrappers проверяют PID/adapter/attempt identity и live ownership; job cell дополнительно несёт свою generation. Observations принимаются только из результата вызова S-owned port на его own wrapper, не из public post_observation/bool API. `closed=True,physical_confirmed=False` допустимо и **не** разрешает drained для entered factory. При native unknown error возвращается safe code/raised safe error без попытки восстанавливать raw resource по ID.

Перед вызовом `launch` на lifecycle lane: matching durable armed ACK; original Budget ещё live, Stop проверен; private once-only launch cell. Lane под коротким собственным gate помечает `call_entered` **до** factory invocation и сохраняет holder/job strong reference. Если Stop успел до этого gate, job возвращает подтверждённый no-call, не выполняет factory. Если gate уже пройден, Stop не объявляет «процесс не создавался»: даже исключение без handle считается unknown creation, armed сохраняется. Нельзя использовать только `is_alive()==False`, отсутствие PID или тип exception как no-create proof.

Mac `start_fixture_attempt` может ждать Popen до возврата handle; lifecycle job остаётся busy/unknown, никакого второго factory/slot. Windows возвращает strong driver с own threads до окончательного CreateProcess outcome; factory return сам не равен started/cleanup. Existing registry/resources Windows продолжают владеть pending I/O. S не вызывает их чужим потоком и не закрывает endpoints из coordinator. Driver stop/renew доступны отдельному platform control lane; no handle — Stop latch ждёт появления handle, а имеющийся G ограничен начальным L/D.

Native reason mapping: user/deadline/lease/storage/shutdown/protocol сохраняются; clock/child передаются как protocol (fail closed), исходный reason остаётся F1/ticket. Stages только из известного C1B STAGES; неизвестный stage → protocol fault, не выдуманный процент. Opaque payload `b'fixture-response'` не преобразуется в B1.

**Observation и candidate:** lifecycle job читает driver view и candidate до close/discard. Сохраняется immutable bytes reference, exact identity и continuous sample capture; candidate допускается только если driver позволил выдачу, native L/D ещё живы, нет Stop/fault. F1 при обработке receipt также должен оставаться live; поздний receipt не оживляет уже stopped C1A. Native cleanup proof отдельно от candidate: отсутствие результата не запрещает честно закончить cleanup.

На natural completion timely candidate + actual physical proof позволяют прекратить native renew. Если observation ещё не обработана, уже принятый Stop не отменяется задним числом. Предыдущий renew job должен вернуться прежде close; его False при уже подтверждённом natural завершении не превращается в storage error. Capture до cleanup обязателен на **обеих** ОС: и Mac discard, и Windows close стирают reply. После capture не вызывать candidate повторно ради восстановления утраченного bytes.

`close_attempt` использует `driver.close(timeout=0)` как bounded attempt в lifecycle lane, без ожидания5s на coordinator. Повтор возможен только после окончания прежнего job; driver может вернуть False, retain всё. Mac physical proof = прежняя view.phase closed +cleanup_confirmed и close True для pump/holder quiescence. Windows = cleanup_confirmed +resources_closed +close True (own threads окончены). Просто close True при known CreateProcess failure/cleanup False не доказывает M exit. Без доступного driver proof такую entered-factory ветку F3 оставляет recovery_required; не читает private native state, чтобы угадать no-create. Это консервативное ограничение доступности, не новая гарантия восстановления.

Для **ни разу не entered factory** no-create выдаёт сам lifecycle state machine после завершения launch job, закрытия future launch cell и окончания всех own platform control/lifecycle operations этого поколения. Для entered factory без полного proof no-call запрещён. `child_closed` F1 публикуется только после actual physical proof и own I/O quiescence; synthetic port может дать это только в явно переносимой fixture приёмке, не за настоящую ОС.

## 8. Drain, release и следующий запуск

Две независимые ветки могут идти параллельно: native Stop/cleanup и SQL settlement/terminal. Durable `armed→drained` требует physical/no-call proof и завершения всех own native jobs. Публикация/её SQL validation могут ещё продолжаться; F2 heartbeat допускает drained. `child_closed` и record_drained не означают автоматически «успех модели».

Следующий claim запрещён до всех пунктов:

1. Тот же launch получил confirmed durable drained (или подтверждённо никогда не arm-ился при clean), no unresolved create/native I/O/control job.
2. SQL run terminal/reconciled. Для succeeded source-backed restore и C1B settlement ACK; для остальных exact terminal receipt. Publication lane завершён, его cells/token outcome согласованы. Admission outcome этой entry тоже известен.
3. Все jobs старого поколения окончены/вычитаны, закрыты future heartbeat/complete/launch. Только после этого lifecycle lane вызывает `owner.release_slot(slot)` ровно один раз.
4. Release True — проверенный probe под продолжающим владеть OS owner. Затем F2 clear_drained с прежним binding/CAS. Unknown clear ACK → только read/тот же idempotent CAS после original job, никакого нового claim до подтверждённого clean.
5. Удалить active generation/тяжёлые refs, сохранить ticket outcome, перейти к следующей зарегистрированной live queued entry. Нельзя брать slot следующего запуска до окончания всех указанных gates.

**Release False:** прежний slot уже инвалидирован native API; его не передавать повторно в release и не считать retained lease. Ledger остаётся drained, S → blocked/recovery_required, owner сохраняется; **нет автоматического нового reserve/probe в этом S**. Startup нового S после фактического завершения прежнего может выполнить собственный fresh probe по правилам §9. Это сознательное ограничение; F3 не добавляет unsafe повтор с устаревшим FD/HANDLE. Exception/unknown release также не даёт clean, даже если OS handle фактически закрылся.

Если arm не выполнялся и ledger остался подтверждённо clean: terminal/reconciliation и завершение всех jobs всё равно обязательны до release; никаких фиктивных armed/drained записей для завершённой без запуска попытки. Если arm мог COMMIT — сначала ledger barrier; clean по одному cached view недостаточно.

## 9. Startup, restart и shutdown

Global strong registry допускает один started S на PID, независимо от новых root/UUID. Несколько инертных constructors допустимы. До старта каждого thread записывается intent; all-lane readiness barrier до первого OS/DB job. Unknown thread start удерживает runtime и блокирует replacement. Умерший coordinator не заменяется новым owner того же F1; G/native L и durable armed дают fail-closed. Полностью ended startup failure можно очистить; `Thread.start` exception сам по себе не такой proof.

Startup: acquire OS owner → F2 database/schema/durability/ledger checks → owner epoch takeover только clean/drained → bounded recovery → slot probe → ready. Engine/session/owner операции на соответствующих lanes, coordinator продолжает servicing Stop. Никакого migration/provisioning/нового root при ошибке. В неподдерживаемой ОС/неподтверждённой V11 startup blocked до admission.

В новой `_queries.snapshot_active` под прежним enqueue advisory lock читать **до18 metadata rows** активных runs: >17, >16queued или >1running/cancel_requested → recovery_required без частичного открытия admission. Освободить advisory до project/document/run locks. Это дополняет F2 queued snapshot, не меняет его. Trust boundary — только S управляет analysis writes в этой установке; обход через старый endpoint/legacy worker не должен быть подключён одновременно. До production wiring это explicit fixture bootstrap.

Старые queued по одному завершаются F2 retire_queued с recheck; old running/cancel_requested никогда не получают claim/heartbeat/новую попытку. Старый reaper допускается, но admission закрыт до подтверждённого отсутствия старых active runs. Initial scan и завершающий scan проверяют отсутствие хвоста; row, неожиданно ставшая running, не пропускается как обработанная. Пока SQL lease ещё жива, startup остаётся starting и ждёт/reaps, не подставляет новый local deadline. При hung reaper SQL lane retained; нет новых engines.

| Ledger после restart | Поведение |
|---|---|
| unprovisioned/missing/malformed/wrong installation | blocked/recovery_required; никакого auto-create clean |
| armed | quarantine независимо от SQL terminal, свободного slot, lease expiry или слов о reboot; no takeover/launch/clear |
| clean | takeover, terminalize старую очередь/reap старые running, проверить slot, затем ready |
| drained | takeover сохраняет старые launch/attempt IDs; закончить только SQL reconciliation, probe/release slot, clear CAS; inference не возобновлять |

Для drained succeeded новый read-only helper восстанавливает SourceBundle/AttemptBundle/ResultBundle прежним codec, сверяет SHA/request/source/binding под ordered locks до/после parsing; данные читаются только с accepted scope и повторной проверкой текущего доступа. Не создавать AttemptControl/CommitPermit/GuardedPublisher старого процесса. Corrupt/missing result/attempt/doc или ownership change, мешающий source-backed read, → recovery_required, не clear. Для nonterminal — existing reaper; после terminal остальные metadata проверяет F2 clear. Drained уже является durable physical evidence, но slot probe и own resource checks всё равно нужны.

Fresh startup slot probe — reserve_slot и release_slot(True) на lifecycle lane без factory; при busy/False/exception startup blocked, не новый slot path. У armed probe вообще не является основанием recovery. Verified boot-generation provider отсутствует и этим циклом не добавляется. Loss of availability в quarantine остаётся release gate.

Shutdown закрывает admission/claim, останавливает все зарегистрированные intents, но продолжает dispatcher, resolving SQL и native cleanup. Pending callbacks/COMMIT/factory/threads после caller timeout остаются strongly retained, возвращается False. Не dispose engine и не close owner, пока их job потенциально работает. Когда own generation закончена — reconcile/drain/release/clean, dispose трёх pools на их lane после session close, close owner на lifecycle lane, закрыть lanes и join coordinator. True только когда threads фактически ended; registry удаляется после этого, не по daemon флагу/phase snapshot.

Startup отказ без запуска собственной generation (например, чужой persisted armed) может освободить только свои завершённые probe jobs/owner/pools и закончить shutdown True, **не меняя ledger**. Это не подтверждение смерти старого G/M и не снятие quarantine. Если собственный entered factory был unknown или release не подтверждён, обычный shutdown не делает такой shortcut.

## 10. Критерий завершения и предел доказательства

Все группы [матрицы](d03-17c1f3-acceptance.md) должны иметь independent cases до source. Переносимый valid B1 fixture → настоящий PostgreSQL/GuardedPublisher success; настоящий native driver → его неизменённый opaque reply → invalid_result с проверенным cleanup/ledger. Эти две цепочки отчётливо разделить. Реальный ML bridge/weights остаются C2, native Windows VM/crash/suspend и Word rendering — отдельные gates; skips не считать доказанными.

Full `bash scripts/check.sh` обязателен. До/после сравнить483 frozen source/test/config hashes (в реализации допускаются только добавленные F3 файлы), V8 schema/revision/counts, пустую ara_test/отсутствие временных БД. Никакой сети/секретов/публикации/рабочих документов в новых тестах. Не закрывать production recovery или editor готовность по количеству тестов.

**После этого дизайна вернуться на Sol 6.1 High**, начать independent acceptance/freeze/red для **D03-17C1F3**. Механические детали внутри указанных путей не требуют нового Astra pass. При реальном конфликте frozen contract — закончить доступный безопасный checkpoint, назвать точный конфликт, не маскировать изменение старых проверок. Остаток самостоятельной работы **26–41 цикла**, F3 ещё не вычтен, дизайн не добавляет новый ID.
