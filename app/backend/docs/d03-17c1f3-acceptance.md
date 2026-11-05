# D03-17C1F3 — независимая композиционная приёмка

**Дополнение от 3 ноября:** [V12 и дополнительные migration checks](d03-17c1f3-timeout-addendum.md). Все 65 зафиксированных F3 cases остаются без изменения; актуальная композиция проверяется на disposable V12 вместо V11. Исторический текст ниже описывает исходный freeze.

3 ноября 2026. Нормативное дополнение к [контракту F3](d03-17c1f3-contract.md). Это **план проверок**, не существующие тесты и не отчёт об их прохождении. Реализация на Sol6.1 High начинается с перевода всей матрицы в новые independent tests и freeze/red; source до freeze не писать. Старые проверки не редактировать.

## Harness и доказательства

Новая одноразовая PostgreSQL V11, synthetic документы, заранее trusted fresh root/DB provisioning в test setup. Main V8 не трогать. Реальный SQL и GuardedPublisher в portable integration, не mock итоговых SQL statuses. Controlled clocks/events/barriers на границах jobs/COMMIT/permit; маленькие реальные waits только для проверки bounded return, не как единственное доказательство порядка гонки. Максимальное ожидание теста заканчивается читаемым assertion/cleanup, не бесконечным join.

Test double PlatformPort явно маркирован fixture; он записывает entered factory/число запусков, gate actual completion/own-I/O и capture before close. Не возвращать произвольный `cleanup=True` через public API; раздельно проверить rejection forged receipt/authority. Fake clock соответствует одному continuous домену на попытку. Native tests используют реальный clock и реальные готовые drivers, без подмены opaque reply.

Вызовы source-private helpers допустимы для точного fault injection; приёмка не копирует алгоритм coordinator и не вычисляет expected через тот же проверяемый helper. SQL success/terminal/fence/result/ledger читаются независимо. Для commit ACK-loss fault срабатывает **после actual COMMIT** ровно один раз; rollback fault — до COMMIT. Snapshot negative outcome под locks проверить отдельным competing connection/barrier.

Неизвестные Thread.start/native jobs, которым нельзя доказать конец в этом test process, изолировать в отдельном test subprocess; сохранять production strong registry semantics, не очищать его вручную ради следующего теста. Завершение test subprocess не является proof production recovery. Нельзя менять frozen старые fixtures/default migrations/check script.

## A. Ограничения, полномочия, servicing

| ID | Сценарий | Независимый критерий |
|---|---|---|
| A01 | Import/constructor, invalid settings/spec/OS | Нет reads secrets/files/network/DB/process/thread; explicit fixture only, safe errors/repr |
| A02 | start twice, конкурентные constructors/start, PID/fork/copy/forged tickets | Один started runtime, один coordinator+5lane threads, чужой ticket/handle не влияет; no replacement |
| A03 | Lane занят callback/SQL/native, caller5s истёк, поздний outcome | Один job+cell, старые refs сохранены, нет второго connection/thread/job; результат принят только прежней generation |
| A04 | Thread.start exception до/после фактического старта, BaseException callback | Unknown retained; startup barrier не допускает side effect без всех lanes; нет автоматического restart |
| A05 | Много view/Stop/heartbeat due/reaper due | Нет backlog/cell growth/новых threads; snapshots не вызывают работу; Stop независимо от stalled admission/publication |
| A06 | Port request сразу после idle tick, wake до cell, scheduler stall >50ms | Active wait≤5ms, нормальный grant не зависит от UI polling; stall не выдаёт late permit; frozen50ms сохраняется |
| A07 | Clock failure/regression/suspend jump, overflow/bool/float | Fail closed, native Stop, нет renewal/grant; известный committed не теряется, auxiliary monotonic не продлевает D |
| A08 | Callbacks/DB/native methods под metadata lock; ошибочные/длинные exceptions | Barrier показывает независимый Stop/view; source/SQL/path/secret/payload не в выводе |

## B. Admission и queue

| ID | Сценарий | Независимый критерий |
|---|---|---|
| B01 | Synthetic saved source, retry terminal, empty/unsupported/corrupt | Старые B3 guards сохранены; exact source/revision; нет запуска по непригодному документу |
| B02 | Same key/same command во время preparation/queued/active и после terminal eviction | Тот же registered ticket/e/D, максимум один run/attempt/create; terminal SQL replay не вызывает provider/inference |
| B03 | Same key/different command; foreign project/document/ticket | Конфликт/404/invalid handle, без Stop/изменения чужого run |
| B04 | 16queue+inflight reservation, один active, busy admission | Нет17queued; rejection до callback; admission payload один, queued metadata-only; FIFO |
| B05 | Stop и deadline во время зависшего provider, затем поздний enqueue | Fast Stop; retained original e; SQL late run закрывается без claim/create; confirmed status только после receipt |
| B06 | Enqueue rollback и actual COMMIT ACK-loss | Пока job не окончен lookup не запускается; после barrier absent/found верны; no second start_saved/new key/anchor |
| B07 | Original COMMIT держит doc lock, lookup начат; lookup timeout/404 | Нет ложного negative из unlocked read/ошибки; retained entry и отсутствие inference |
| B08 | Negative admission, release payload/capacity, repeated completed ticket | Нет вечного S-cache, старый ticket стабилен; unresolved key нельзя забыть/переякорить |
| B09 | Неизвестный незарегистрированный active replay | recovery_required, не присвоение нового срока/claim_next |

## C. Claim, lease и запуск

| ID | Сценарий | Независимый критерий |
|---|---|---|
| C01 | Slot before claim, claim before arm, arm ACK before factory | Записанный trace+DB barriers доказывают порядок, один attempt/launch; no global claim_next |
| C02 | Claim ACK-loss с committed running либо absent queued | Fixed IDs/e/s; read resolution без повторного claim/inference; storage Stop сохраняется |
| C03 | Arm rollback/actual COMMIT ACK-loss; Stop/D до/после ACK | Factory0 до confirmed matching armed; no-create drain только при доказанном не-вызове |
| C04 | Native factory завис/бросил без handle; Windows handle до create outcome | Armed/slot/strong refs не сброшены; no second create, terminal SQL не снимает fence |
| C05 | Claim задержан, D_enqueue раньше SQL deadline; ACK поздно | D=min прежних bounds; guard не удвоен; нет нового300s/lease после позднего ACK |
| C06 | HB started/received/processed разнесены; lower bound/old ACK | Только receipt heartbeat_at, свежий processing sample, expiry не оживает, один LeaseTicket |
| C07 | Native renew False/busy/late/unknown, SQL HB уже принят | Старый native L действует до actual receipt; повтор только того же bound, никакого нового HB ради обхода |
| C08 | Natural completion во время renew, capture/close/control job race | Candidate захвачен до close; late Stop не отозван; native False после natural proof не ошибочно считается DB failure |

## D. Local terminal bridge и SQL publication

| ID | Сценарий | Независимый критерий |
|---|---|---|
| D01 | Queue D истёк при SQL wall deadline ещё live | SQL timed_out/deadline_exceeded, no attempt/result/create; forged UUID/reason не может вызвать запись |
| D02 | Claimed unarmed, armed no-call и entered factory: одинаковый local deadline | Exact terminal, но clean/drained разрешены только по своему physical/no-call proof; entered unknown остаётся armed |
| D03 | User/lease/clock/storage/shutdown/child/protocol причины; повтор ticks | Table §6, first reason стабилен, SQL terminal не перекрашивается, прежние constraints/stage/fence/timestamps |
| D04 | Stop до F1 reserve/после offered до take/после take | До reserve — нет Result. Offer уже зарезервировал право: Stop после offer может встретить actual take/COMMIT; успех сохраняется. Abandoned недоставленный token откатывается, не считается unknown COMMIT |
| D05 | Unknown COMMIT ещё работает; Stop и D | Finalizer не стартует, RAM/native Stop работает, retained publisher/token, no cancelled ACK |
| D06 | Unknown COMMIT действительно succeeded и действительно rolled back | C1B reconcile единственный resolver; success source-backed сохранён, rollback затем exact local terminal |
| D07 | C1B поставил cancel_requested по local deadline до SQL wall timeout | Bridge timed_out; cancel_requested не ошибочно означает user cancel; already terminal cancelled/failed сохраняется |
| D08 | Settle timeout до/после выполнения, unknown→committed, committed→unknown fallback | Exact pending pair сначала flush; один token, stable committed; no direct F1 private cell edits |
| D09 | **Rollback settled, ACK потерян, затем reaper terminal** | Flush rolled_back ACK; seal publisher; read barrier видит terminal; не посылается conflicting terminal для old token |
| D10 | Resolved committed ACK-loss → sealed publisher/read restore | Exact reply/source/result SHA, no inference/new publisher; corruption не очищает fence |
| D11 | Resolved rollback, затем неожиданный success/result в БД | recovery_required; не подмена outcome/authority и не выдача success |
| D12 | Exit authority до/во время/после publication job; stale/copy/fork/другой owner | Issuance разрешён только после generation seal и barriers; invalid handle без SQL mutation |
| D13 | Terminal bridge actual COMMIT ACK-loss | Тот же issued authority после job завершения возвращает тот же terminal; нет новой причины/попытки |
| D14 | Ownership сменился, document/attempt удалён, metadata повреждены | Нет чужой записи/доступа; ownership_changed только exact accepted identity; невозможный recheck сохраняет fence |
| D15 | Valid synthetic B1 reply → настоящий GuardedPublisher/PostgreSQL | Один source-backed Result/succeeded; per-source/request constraints; pipeline не имитирует SQL success |
| D16 | Invalid/oversize/corrupt reply/source | Прежние B1/B2/C1B отказы, zero false success; исходный DOCX/сохранения неизменны |

## E. Cleanup, recovery и shutdown

| ID | Сценарий | Независимый критерий |
|---|---|---|
| E01 | Candidate ready, M exited, EOF или own I/O ещё pending | Нет child_closed/drained/нового launch; каждый proof проверяется независимо |
| E02 | Physical finished раньше SQL / SQL terminal раньше physical | В обеих перестановках следующий launch ждёт оба исхода; terminal не proof exit |
| E03 | Record_drained до/после COMMIT ACK-loss | Same binding/CAS read resolution, no повтор factory/slot release до согласования |
| E04 | Release True / False / exception после invalidation | True перед clear; False/unknown не повторяет старый lease, не clear, no automatic fresh probe в том же S |
| E05 | Clear actual COMMIT ACK-loss, следующий ticket готов | No next claim до confirmed clean; stale generation/job receipt не касается следующего launch |
| E06 | Crash после claim до arm / после arm до factory / после physical до drained COMMIT | Clean unlaunched старый run не resumed; armed во всех последних ветках quarantine, даже free slot/terminal |
| E07 | Crash после drained COMMIT / после clear COMMIT | Drained только restore/reap/probe/clear, clean normal startup; old inference/permit не восстановлены |
| E08 | Startup queued/running/cancel_requested; expired/nonexpired;18active/>1running | Bounded scans/recheck, старые queued retired, живые SQL leases не переякорены; ready только после active absence |
| E09 | unprovisioned/missing/malformed/wrong-installation/armed | No auto provision/reset/migrate/root switch; blocked metadata safe; новый UUID не обход |
| E10 | Drained succeeded source/result corruption или inaccessible scope | Source-backed restore вне locks + final recheck, никакого clean по одному succeeded flag |
| E11 | Shutdown с зависшими admission/SQL/native job, поздний return | Общий5s или меньший caller timeout, False+strong retention, cleanup продолжается, no premature dispose/close |
| E12 | Shutdown clean, повтор, startup отказ до own launch | Threads фактически ended до True/registry release; persisted quarantine не сброшен даже если own cleanup закончен |

## N. Native evidence отдельно от portable

| ID | Где | Критерий |
|---|---|---|
| N01 | macOS + synthetic DOCX + disposable V11 | Настоящий existing driver выдаёт opaque bytes; F3 не подменяет их, C1B invalid_result, подтверждённый physical cleanup/drained/clean; request/spec bindings |
| N02 | macOS Stop/lease/shutdown + actual root/slot | Никакого второго native launch при pending cleanup, capture before discard, next launch после чистого закрытия; платформенные skips/ошибки назвать |
| N03 | Windows VM + тот же сценарий | Existing E1–E4 handles/threads, real Job/EOF cleanup, opaque reply rejected; без Windows — явный skip, portable tests не считаются этим evidence |
| N04 | Portable driver-shaped doubles для обеих ОС | Сигнатуры/normalization/reason mapping/close False проверены; это только adapter wiring, не proof Windows/boot safety |

Production crash/suspend/boot recovery, installer provisioning, Word rendering и настоящие weights не закрываются F3. В результате раздельно указать portable SQL success и native invalid_result, доступные native runs/skips, текущую main V8, hash preservation и фактический full gate. Freeze commit и red подтверждаются только при реализации, не выдумываются в design result.
