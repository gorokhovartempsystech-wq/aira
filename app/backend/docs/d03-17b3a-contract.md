# D03-17B3A — принятие и чтение DOCX analysis run

1 ноября 2026, Sol6.1 High, после B2B d798d77. F06/F07/F12. Текущий scope и B2 design обязательны. Выполнить scoped durable enqueue/replay/retry/read без worker/HTTP/model. Один ID, source только `src/ara/docx_analysis_runs/`, собственные `tests/docx_documents/test_analysis_runs_start_*.py`; новая frozen `tests/acceptance/test_docx_analysis_runs_start.py` и этот контракт фиксируются родителем до source. Модели/V10/B1/B2B/старый API/tests/runner/dependencies неизменны. Результат и queue links после gate; main V8 не мигрировать.

## API и доверенная граница

```
start_saved(runtime:DocumentRuntime, *, client_request_id:UUID,
    command:SavedCheckCommand, target_provider:Callable[[],SavedTarget],
    execution:ExecutionSpec, limits:CodecLimits|None=None, queue_limit:int=16) -> StartOutcome
retry_run(runtime:DocumentRuntime, *, client_request_id:UUID,
    command:RetryCheckCommand, execution:ExecutionSpec,
    limits:CodecLimits|None=None, queue_limit:int=16) -> StartOutcome
get_run(runtime, *, document_id:UUID, run_id:UUID) -> RunSummary
get_source(runtime, *, document_id:UUID, run_id:UUID, limits=None) -> SourceBundle
```

Runtime — существующий server-owned local context, не новая авторизация. target_provider — **trusted backend dependency**, будущий HTTP пользователь не передаёт функцию/bytes/SavedTarget/execution/queue_limit. Типичный provider вызывает registry.saved_target(...) с сохранёнными command IDs/counters. Returned SavedTarget exact class/revalidated, все registry/document/session/save-command IDs/counters/revision/SHA равны команде. Один его immutable data buffer используется целиком; не GET latest/current. Сам факт создания DTO Python caller не доказывает registry authority; её обеспечивает выбранная сервером dependency. Никакого нового endpoint в этом цикле.

Public DTO frozen/slotted. `StartOutcome(summary:RunSummary,replayed:bool)`. RunSummary: run_id/document_id UUID, storage_revision/accepted_order int, source_sha256/snapshot_sha256/profile/policy_version/execution_spec_sha256 str, client_request_id UUID, start_kind str, retry_of_run_id UUID|None, status/stage/execution_kind str, created_at/deadline_at datetime, finished_at datetime|None. Только эти metadata, без source/manifest/command/execution bytes, владельца, models_version/raw error text. Validate exact types, allowed values/digests/bigint/finite aware times/deadline+300 и status/finished shape до возврата; no implicit coercion. Это raw persisted status; deadline materialization/reaper — B3B, не притворяться работающим таймером.

## Replay до RAM/config dependencies

Проверить runtime/command/client_request UUID/queue_limit1..16/limits/каноническую команду. Первой **scoped** SQL transaction project→document→key lookup проверить durable(command_data,command_sha256) c small-only column projection. Exact existing command/hash возвращает исходный summary при любом status; current source/registry/target_provider/execution pack не нужны. Execution и provider validity проверяются только для fresh request; replay работает даже с execution=None/provider=None после restart. Altered body под тем же ключом409 idempotency_conflict. Stored command invalid hash/canonical/binding —500 storage_error, не ложный409.

Возврат summary без чтения BYTEA source/snapshot/execution; маленькая command≤16KiB нужна только replay. Публичный get_run вообще metadata-only. First lookup IDs/scopes не даёт доступа чужому project. Не принимать owner/project из command.

Fresh request: запомнить DB clock из первой transaction до provider/extraction. Затем отпустить SQL locks. Provider ровно один раз, без project/doc locks. Подтверждённый SavedTarget и detached bytes не подменяются при параллельном save. Сверить target identity/sha/data; build_visible_snapshot с command identity и capture_source(B2B). Execution pin проверяется на этом шаге, не после insert.

Fresh retry: scope-check parent run, нужен terminal succeeded/failed/cancelled/timed_out того же документа. Взять его pinned source/revision через get_source и проверить B2B. Новую snapshot/command/execution строить по этой source identity, с **новой** текущей trusted ExecutionSpec; не current DOCX и не прежняя попытка. Нет auto-retry inference. Parent absence404, active parent409 analysis_in_progress. Перед commit вновь проверить terminal parent и source identity. Retry самого себя невозможен: ID нового run генерируется сервером.

Если provider/preparation завершается ошибкой, сначала ещё раз scoped recheck durable key: concurrent identical enqueue мог commit после первого lookup. Exact accepted replay имеет приоритет над истечением RAM/config. Если ключа по-прежнему нет — исходная safe ошибка. Эта проверка не создаёт run/source/key receipt. При DB недоступности нельзя выдумывать replay/успех.

## Enqueue transaction / order

Взять `pg_advisory_xact_lock(1095911745,170301)` **до row locks**: namespace локальной очереди DOCX analysis. Затем project FOR SHARE (owner stable) →document FOR UPDATE→key/active lookup. Все будущие enqueue данного семейства используют эту пару; никаких session-level advisory locks. Не копировать старый worker обратный порядок. Reads без admission lock используют project→document FOR SHARE. Initial queue_limit≤16 — внутренний server bound на всю эту БД, не product max/на один процесс.

В финальной transaction повторить replay (если совпал — вернуть прежний summary даже при active/queue limit); затем один active run/document queued/running/cancel_requested, другой ключ409 analysis_in_progress и не занят. Cap count queued на всю БД; если уже queue_limit →503 analysis_queue_full, retryable. Старые expired queued до B3B reaper всё ещё занимают очередь — этот этап не меняет status сам. Проверить clock freshness/deadline до записи и после flush до commit gate. `created_at` — начальный DB time перед preparation, `deadline_at=+300s`; fresh now>=deadline →408 analysis_deadline_exceeded, ничего не принято. Clock backwards(now<created)→503 analysis_clock_error. Время fsync после decision не обещается как нулевое.

Положительный accepted_order=max(existing document order)+1 под document lock, без sequence; MAX_BIGINT→409 analysis_history_exhausted. Новый server UUID run_id; status/stage queued,fence0,attempt/result/error NULL, explicit updated/created/deadline. Source insert только если document+SHA отсутствует; при existing сравнить hash **и bytes**, mismatch500 storage_error, не overwrite. Извлечение/codec не под SQL/actor mutex; здесь только готовые bounded buffers и короткая запись. Source+run+key атомарны: rollback не оставляет orphan source или занятого ключа.

Транзакция возвращает prepared DTO только после commit; caller engine не закрывается. Unknown commit→safe storage error/503, retry same key читает принятое без нового source/run/order/provider и не продлевает deadline. Не повторять inference/создание автоматически. Metadata/list не изображают готовый результат, staged worker ещё отсутствует.

## Scope / source read / errors

Scope всегда current document.project_id==runtime.project_id и project.owner_id==runtime.user_id; чужое/unknown404. accepted owner/project — immutable pin при enqueue. Transfer во время provider/preparation перепроверяется финальным lock, rollback без записи. Read старого source/result разрешён текущему владельцу документа, не старому owner; active ownership fencing — B3B. Полученный snapshot чтения авторизован в момент scoped capture; не держать SQL lock во время full codec validation.

get_source under scope копирует связанный source+run buffers и metadata; отпускает locks, restore_source(B2B) проверяет bytes/manifest/command/execution; corruption500 storage_error. Metadata get_run не тянет source/current bytes и остаётся доступным при повреждённом source. Изменённый current не меняет pinned source.

Переиспользовать DocumentError с static messages:422 validation_error/unsupported_analysis_content/empty_document;413 analysis_limit_exceeded;409 idempotency_conflict/saved_target_conflict/analysis_in_progress/analysis_history_exhausted;408 analysis_deadline_exceeded;503 storage_unavailable/analysis_queue_full/analysis_clock_error(retryable);500 storage_error. Existing safe DocumentError от registry provider сохранить. Прочий provider exception→500 storage_error без тела. OperationalError/commit loss→503 storage_unavailable; SQLAlchemyError/invalid stored data→500 storage_error. Не печатать diagnostics/SQL/bytes, не ловить BaseException. Никакого secret/config/model loading.

## Freeze / checks

Новая acceptance red до source. Real disposable PG: durable restart replay до provider/config; altered key body; foreign scope; exact saved-target matching и parallel newer current; complete source/admission отказ без rows; one active race, same-key race, queue cap cross-doc/project; atomic rollback/source collision; immutable dedup и accepted_order; terminal retry source vs current; metadata-only SQL projection; ownership transfer during provider; timed preparation/deadline (controlled DB clock seam в собственных tests без реального sleep5min); unknown commit reconciliation. Source-backed stored corruption safe/no result fallback. Fresh import no runtime I/O; один integration через настоящий registry.saved_target. Targeted +полный scripts/check.sh, baseline рабочих баз, local result/commit; потом B3B на Sol по отдельному контракту.
