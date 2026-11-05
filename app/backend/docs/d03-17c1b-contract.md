# D03-17C1B — guarded SQL publication и reconciliation

1 ноября 2026, Sol6.1 High, после C1A f38f0d9. F06–F08/F12, [C1](d03-17c1-design.md), current-product-scope и прежние B1/B2/B3 обязательны. Один цикл: связать C1A publication permit с атомарным SQL результатом. Без child/IPC/HTTP/scheduler/model, изменения DDL или основной БД.

Allowed: новые `src/ara/docx_analysis_runs/guarded*.py`, additive exports в __init__, новая frozen `tests/acceptance/test_docx_analysis_guarded.py`, собственные `tests/docx_documents/test_analysis_guarded_*.py`, этот контракт до freeze, result/queue/C1 status после gate. Прежние B3B/C1A modules/tests/контракты, runner/tasks/progress/dependencies не менять.

## API

`ara.docx_analysis_runs.guarded`:

- `PublicationPort` — ABC trusted backend port: `view()->ControlView`, `reserve()->CommitPermit|None`, `settle(permit,*,outcome:str)->ControlView`. Методы bounded, не вызывают SQL/процессов. Позже C1F dispatcher реализует этот port. Это не клиентский capability/API и не sandbox против кода в backend.
- `DirectPublicationPort(control:AttemptControl,*,clock:Callable[[],int])`: explicit standalone/test adapter, clock без default; конструктор не вызывает clock. Не обещает сериализацию timestamp sampling между потоками; C1F использует dispatcher port.
- `GuardedPublisher(engine,claim:WorkerClaim,*,port:PublicationPort,limits=None)`: inert constructor проверяет Engine/claim/limits и exact port view identity == claim run/attempt/worker/fence. Не читает БД/секреты/часы, не запускает threads. Не копируется/не сериализуется; repr скрывает bytes/engine/port.
- `.complete(*,reply:bytes)->WorkerUpdate`, `.reconcile()->WorkerUpdate`.

Уточнение sketch `complete_guarded` из C1: состояние unknown permit/result/reply хранится в одном publisher на attempt, поэтому выбран объект с двумя операциями. Потеря ACK не должна терять exact local permit. Не создаёт persistent нового состояния/DB objects. До первого выданного permit reconcile только read/materialize durable state и возвращает accepted=False; никакого replay inference. Publisher не отдаётся frontend. Старый complete_attempt внутри него не вызывается.

Операции publisher защищены nonblocking mutex: конкурентный вызов409 publication_in_progress, Stop обслуживается напрямую controller/dispatcher независимо. Один publisher на owned attempt обеспечивает будущий supervisor. Private buffers bounded прежними CodecLimits; retained только один reply≤4MiB/expected result digest/current permit, без накопления generation history. После выдачи первого permit другой reply409 publication_conflict, без overwrite. Constructor не запоминает claim source/request как authority.

## Complete

Повторно проверить claim и port identity перед каждой операцией. Прочитать DB records через B3B ordered-lock helpers, восстановить source/request, fully validate result B2B вне SQL locks. Invalid source/reply materializes прежний failed code, previous successful results intact. Existing success — full B2B read/replay с exact reply; no new permit, никакого изменения истории. Malformed bytes/type/limits422, finite bounds перед validation, oversize не копировать. Ошибки sanitized DocumentError, no raw data/exception text.

Final transaction: project SHARE→document UPDATE→run UPDATE→attempt UPDATE, recheck persisted owner/token/fence/lease/deadline/source/request exact bytes и свежий DB clock после buffer reads. Только running/fence1 допустим. **Затем port.reserve**; None → no result/no success, вернуть accepted=False с фактическим SQL state (не выдуманный cancelled). Durable cancel/OS cleanup в C1F. Permit → retained reply/result digest, Result+succeeded/fence2/deferred checks/COMMIT как B3B. ACK → port.settle committed и accepted=True.

Stop до reserve исключает публикацию, Stop после reserve допускает pending outcome. SQL cancel/deadline/owner loss до final gate исключает result. Порт должен подтверждать child_closed по C1A; source/claim DTO подмена не даёт запись. Второй identical completion, успевший получить success, проверяет full exact bundle, не только digest. Нельзя выдать success из uncommitted RAM.

Любая ошибка после выдачи permit консервативно оставляет unknown (включая flush/deferred/commit failures). Пробовать port.settle unknown; если port ошибся, всё равно сохранить pending внутри publisher. OperationalError503, прочая storage/port ошибка500; failed commit не возвращает accepted. До permit storage exception не создаёт pending. Следующий complete сначала reconcile; только после доказанного rollback можно повторить публикацию того же reply, с новым permit, в прежних бюджетах.

## Reconcile

Сначала новая transaction с тем же ordered-lock barrier. Unlocked read «result нет» не доказывает rollback. Проверить persisted attempt/worker identity, materialize B3B expiry/owner loss; другой token не даёт чужой результат. Получение locks должно сериализоваться с прежним writer transaction.

- exact succeeded: восстановить source/request/result и B2B envelope вне locks, затем подтвердить exact bytes/digest/identity через B3B replay gate. Сравнить expected result digest **и raw reply** с retained, иначе corruption500; не переписывать history. Только после этого settle committed. Даже если Stop пришёл после permit, вернуть фактический success.
- still running без result после barrier: прежний COMMIT не состоялся. Если local stop_requested, сначала atomically durable cancel_requested/fence2 с прежней lease, затем settle rolled_back (controller остаётся stopped). Иначе settle rolled_back, accepted=False, no new write/inference; следующий complete может взять новый permit.
- terminal failed/cancelled/timed_out или cancel_requested: сохранить durable state, settle terminal; не оживлять run. В этом API terminal port означает «публикация закрыта», не обещание physical exit и не fabricated SQL cancelled.
- DB unavailable/lock error: сохранить unknown/pending,503. Stored corruption после success:500, не reset status/result/permit и не inference.

Barrier transaction должна успешно закончиться до local rolled_back/terminal settle. Stop может прийти после проверки RAM flag в barrier: повторно проверить control после rollback settlement; если появился stopped, выполнить durable cancel отдельной scoped transaction до возврата, а при ошибке сохранить stop для будущего reconcile. C1F повторяет cancel intent до durable confirmation. Никогда не трактовать текущий RAM view как proof SQL scope.

## Frozen acceptance до кода

PG fixture synthetic world на latest disposable schema. Freeze/red на отсутствии API; старые тесты unchanged. Проверки: success/replay/fixture counts; no child_closed; Stop before reserve и в unlocked validation; Stop после reserve+commit success; invalid reply/source; SQL cancel/deadline/owner races; forged claim/foreign port; no mutation before permit; before/after actual COMMIT failure с retained unknown; locked absence ждёт незавершённую transaction; unknown+Stop rollback→durable cancel без результата, unknown+Stop commit→success; concurrent same publisher busy; source/result corruption500/no rewrite; no unguarded complete; constructor/import inert; snapshots/raw bytes не logs/repr.

Targeted acceptance+own cut-point tests, затем `bash scripts/check.sh`, read-only main schema/count baseline, result/local commit. Никакой миграции/очистки ara_dev/ara_test, использования secrets/archive/Word/model или push. Далее C1C wire на том же Sol6.1 High по отдельному контракту, если нет архитектурного конфликта.
