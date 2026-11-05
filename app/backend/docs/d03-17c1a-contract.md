# D03-17C1A — pure бюджет и арбитр Stop/publication

1 ноября 2026, подготовлен на Astra 6 High. **Следующий implementation цикл на Sol 6.1 High.** Основание: [C1 design](d03-17c1-design.md), B3B `7cd3b54`. F06/F07/F08/F12. Этот контракт не означает, что код/приёмка уже реализованы.

## Scope и разрешённые пути

Одна ответственность: детерминированная локальная арбитрация времени, Stop и права начать final SQL publication. Потокобезопасный pure controller без чтения часов/SQL/процессов. Все времена передаются явно; clock/OS/SQL proof — будущие adapters. Новый controller не заменяет durable fence и не подтверждает отмену самостоятельно.

Allowed implementation:

- новый `src/ara/docx_analysis_worker/__init__.py` с inert namespace;
- новый `src/ara/docx_analysis_worker/control/`;
- новая frozen `tests/acceptance/test_docx_analysis_control.py`;
- собственные `tests/docx_documents/test_analysis_control_*.py`;
- этот контракт/acceptance до freeze, затем только result `docs/d03-17c1a-result.md` и очередь/статус в C1 design после gate.

Не менять B1/B2/B3, models/migrations/старые tests/dependencies/check.sh/runner/tasks/progress/AGENTS. Никакого subprocess, DB/network/files/environment I/O, clock reads, sleeps, фоновых threads/tasks при import или создании controller. Сам mutex стандартной библиотеки допустим. Не добавлять endpoint или wire codec в этот цикл. C1B–F требуют отдельных frozen contracts.

## Exact API

Импорт: `ara.docx_analysis_worker.control`.

```python
@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    run_id: UUID
    attempt_id: UUID
    worker_instance_id: UUID
    claim_fence: int  # exact int == 1

@dataclass(frozen=True, slots=True)
class Budget:
    deadline_ns: int
    lease_ns: int
    last_ns: int
    guard_ns: int

@dataclass(frozen=True, slots=True)
class ControlView:
    identity: AttemptIdentity
    phase: str
    stop_requested: bool
    stop_reason: str | None
    child_closed: bool
    deadline_ns: int
    lease_ns: int
    last_ns: int

class ControlError(Exception):
    code: str  # validation_error | invalid_permit | conflicting_outcome

def make_budget(*, started_ns: int, received_ns: int,
                remaining_deadline_ns: int, remaining_lease_ns: int,
                guard_ns: int = 50_000_000) -> Budget: ...

class AttemptControl:
    def __init__(self, identity: AttemptIdentity, budget: Budget): ...
    def view(self) -> ControlView: ...
    def tick(self, *, now_ns: int) -> ControlView: ...
    def request_stop(self, *, now_ns: int, reason: str = "user") -> ControlView: ...
    def acknowledge_lease(self, *, started_ns: int, received_ns: int,
                          remaining_lease_ns: int) -> ControlView: ...
    def mark_child_closed(self, *, now_ns: int) -> ControlView: ...
    def reserve(self, *, now_ns: int) -> CommitPermit | None: ...
    def settle(self, permit: CommitPermit, *, outcome: str,
               now_ns: int) -> ControlView: ...
```

`CommitPermit` — exported type для аннотации, непрозрачный объект, создаётся только reserve. Авторитет — identity exact object, записанного в controller; public constructor/копия/replace/чужой controller/старое поколение не выдают право. Нельзя восстановить permit по строковому ID, pickle или DTO. Frozen/slotted snapshots не раскрывают lock/internal permit. Repr/error содержат только безопасные тип/код/ID/фазу, не произвольный invalid input. `AttemptControl`/permit copy/deepcopy/pickle отвергаются, чтобы копирование не создавало второго владельца. Private Python internals не security boundary от произвольного кода процесса.

## Exact validation и время

UUID — exact `uuid.UUID`, fence — exact int1. Counters — exact int, не bool/float/str, в `[0, 2**63-1]`; overflow при сумме отвергается до изменения состояния. `remaining_deadline_ns` от1 до300_000_000_000, remaining lease от1 до15_000_000_000 и не больше remaining deadline; guard от0 до50_000_000. `received_ns >= started_ns`. Неверные вложенные DTO/constructor bypass проверяются повторно при создании controller. В Budget `lease<=deadline`, `deadline-last<=300_000_000_000`, `lease-last<=15_000_000_000`, guard в диапазоне, last/counters корректны; уже истёкший budget допустим и сразу создаёт stopped. DTO не доказывает DB clock: trusted C1F adapter отвечает за правильные исходные durations.

`D=max(started, started+remaining_deadline-guard)`; `L=min(D,max(started,started+remaining_lease-guard))`; `last=received`. Никогда не якорить сроки к received. Разница `deadline-claimed_at` получается из DB timestamps позднее в C1F без float; pure слой не импортирует B3/SQLAlchemy. Guard применяется один раз при каждом новом разрешённом lease, не вычитается повторно при tick.

Сравнение `now>=D` означает deadline, иначе `now>=L` — lease. Равенство уже истекло. `now<last` — clock fault: stop, last не уменьшается. При нормальном tick last=now. D неизменен всю жизнь controller. Deadline и lease — local conservative bounds, не persisted SQL timestamps/status.

`acknowledge_lease`: единственный trusted caller передаёт только accepted B3 heartbeat, с single in-flight discipline. Сначала проверить exact inputs/received>=started/overflow; затем tick(received) по **прежним** bounds. Если controller всё ещё open, новый `L=min(D,max(started,started+remaining_lease-guard))`; ACK сам не должен быть просрочен относительно нового L. Если new L уже истёк — stop lease; если он меньше старого, сократить срок, не молча увеличить. В committing/unknown/stopped/terminal/succeeded lease не продлевается. Поздний ACK не оживляет control, даже если в SQL heartbeat принят. started может быть раньше last из-за параллельного tick во время DB call; received должен соблюдать monotonic порядок.

`view()` не читает часы и не материализует expiry. Все мутирующие методы, кроме authoritative committed settle, применяют tick до решения. Exact validation ошибок происходит **до** любой мутации; malformed request не должен даже изменить last. Для settle с подтверждённым committed результат выигрывает expiry/Stop, потому что SQL факт уже состоялся; время проверяется на тип/range, last не откатывается, выявленная local clock fault не превращает успех в отмену. Stale timestamp от параллельного caller также fail-closed; C1F сериализует измерение now через control dispatcher, не отправляет старые timestamp samples из DB threads. В concurrent pure tests использовать управляемое общее время либо проверять допустимую безопасную остановку при stale sample.

## Состояния

Фазы exact: `open`, `stopped`, `committing`, `unknown`, `succeeded`, `terminal`. Stop reasons exact: `user`, `deadline`, `lease`, `clock`, `storage`, `child`, `shutdown`, `protocol`. Первый зафиксированный reason сохраняется; при одном tick deadline проверяется раньше lease. Все причины запрещают новые вычисления/публикацию одинаково. Stop, пришедший в succeeded/terminal, возвращает unchanged view (фактический terminal не меняется).

- На init open, child_closed=False, stop_requested=False; tick по budget.last может сразу дать stopped.
- request_stop ставит необратимый stop_requested/reason. В open → stopped. В committing/unknown оставляет фазу: операция публикации уже допускается и имеет неопределённый/ожидаемый исход. Это pending, **не** локальный cancelled ACK.
- mark_child_closed после tick фиксирует child_closed=True, повтор idempotent. Это утверждение trusted OS adapter о clean exit+EOF+принятом единственном result; pure слой OS не проверяет. Оно не снимает stop и само не разрешает публикацию. Флаг можно зафиксировать и после Stop для cleanup; reserve всё равно запрещён.
- reserve после tick даёт один permit только в open, !stop_requested и child_closed=True. Иначе None; duplicate reserve не даёт второй permit. Фаза committing меняется в том же critical section.
- settle принимает exact текущий permit (либо exact последний settled для описанного ниже idempotent replay) и outcome из `committed`, `rolled_back`, `unknown`, `terminal`; input validation/foreign token errors не меняют control. SQL authority вызывающего service вне pure scope.
- committed из committing/unknown → succeeded, независимо от Stop/expiry. Повтор exact committed с тем же permit idempotent. Не создавать новый permit после success.
- unknown из committing → unknown; повтор unknown idempotent. После committed прежний запоздалый unknown — безопасный unchanged success. Никогда не возвращает open.
- rolled_back означает доказанный rollback либо отсутствие result после ordered-lock reconciliation. Из committing/unknown: выполнить tick, затем stopped при stop_requested, иначе open. Прежний permit погасить. Повтор rolled_back того же последнего завершённого permit idempotent до выдачи следующего; после нового reserve старый permit invalid. Отмена при still-running SQL затем обрабатывается C1B, pure слой не пишет БД.
- terminal означает подтверждённый failed/cancelled/timed_out в SQL. Фаза terminal, никаких новых permits. Повтор exact terminal idempotent. Pure слой не определяет конкретный SQL terminal code.
- Conflicting terminal outcomes одного permit (committed↔rolled_back/terminal) — conflicting_outcome; не переписывать прошлый факт. unknown→terminal/committed/rolled_back допустим. После rolled_back поздний unknown — unchanged, пока permit ещё известен; он не открывает unknown заново.

Stop-before-reserve и reserve-before-Stop — оба допустимых concurrent порядка. В первом не бывает permit, во втором Stop остаётся pending до settle. Нельзя держать mutex во время финальной SQL transaction, иначе «Стоп» зависнет вместе с БД. Никаких callbacks, acquire foreign locks или неограниченных очередей внутри controller; хранить только текущий и последний settled permit, не всю историю.

## Frozen acceptance до реализации

Создать и зафиксировать acceptance, получить red на отсутствующем модуле/API; не ловить ImportError как skip/pass. После freeze не менять acceptance/контракт без явного основания/авторизации; исправления реализации в allowed paths. Собственные edge tests не подменяют frozen tests.

1. Budget latency не увеличивает сроки; boundary0/MAX/overflow, exact int vs bool, invalid UUID/fence/DTO, expired-on-init, guard saturation, no mutation on invalid inputs.
2. Deadline equality и lease equality, priority deadline, backwards clock, forward jump после suspend; late heartbeat и ещё живой ACK с smaller lease, ACK после stop/unknown, повторный tick не уменьшает D.
3. Нет reserve до child_closed; повтор mark; reserve один раз; no permitting after Stop/storage/lease/deadline/protocol; mark_child_closed после Stop не открывает gate.
4. Stop→reserve denied; reserve→Stop pending→commit success; unknown→Stop→locked rollback stopped; unknown→commit success; rollback без Stop→новый permit с тем же D; rollback после expiry не даёт retry.
5. Wrong/forged/copied/cross-controller/stale permit rejected; invalid outcomes атомарны; bounded retention; idempotent known settlements и conflicting outcomes.
6. Barrier-based concurrent tests: два reserve — максимум один; Stop против reserve; Stop против rolled_back; heartbeat против expiry. Проверять допустимые linearizable исходы, не порядок thread scheduling и не sleep-based случайность. Никакого переиспользования permit после результата гонки.
7. Fresh import/constructor не читает файлы/env/clock, не делает network/SQL/process/background work; patched forbidden calls доказывают это. Repr/исключения не включают sentinel invalid input. Copy/pickle controller/permit не создаёт новую authority.

Обязательные проверки: targeted acceptance + own tests; затем `bash scripts/check.sh` (Ruff/format/full pytest). Результат фиксирует реальные числа, limitations и unchanged runtime baseline. Main ara_dev/ara_test не мигрировать/очищать; full gate использует только disposable test БД. Локальный commit через обычное разрешение sandbox в рамках standing workflow; никакого push.

После зелёного C1A переходить к отдельному C1B contract на **Sol 6.1 High**, без нового запроса «дальше?», если не выявлено архитектурного противоречия. C1A не доказывает работающие Stop/SQL/process в приложении; это первый проверяемый компонент.
