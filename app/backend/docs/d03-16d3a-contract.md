# D03-16D3A — checkpoint controls и close с сохраняемым attempt

31 октября 2026, после c093e90/6b813e9, Sol 6.1 High. F05/F11/F12, d03-16d-design.md §§4–7. Соединить RAM с существующим PUT checkpoint. Без dirty current save (D3B), новых routes/миграций или UI. Прежние B/C методы и native source не менять.

## API

Registry.checkpoint, Registry.save, Registry.reconcile принимают keyword document_id/session_id/command_id/expected_command_sequence/expected_session_revision, возвращают EditorView. Registry.close принимает те же поля и mode=checkpoint|release_local (default checkpoint), возвращает новый frozen/slotted ClosedEditor(registry_id,document_id,session_id,mode,checkpoint_revision:int|None). Reconcile завершавшего close может также вернуть ClosedEditor.

save в этом подцикле обслуживает только native dirty=false: selection checkpoint, без storage revision/SQL receipt/mark_saved. Dirty ->409 editor_save_requires_commit до attempt/записи/sequence; D3B расширяет тот же метод. До окончания D3/E этот API не объявляется полным пользовательским сохранением.

checkpoint записывает и dirty working exact bytes/selection/origin, не current. close(mode=checkpoint) всегда делает такой checkpoint, включая clean, затем освобождает RAM. Recovered pending требует reconcile D3B: здесь409 editor_operation_pending без записи. close(mode=release_local) — явное терминальное освобождение только RAM, без DB write/cleanup/утверждения «не сохранено». Разрешено pending/conflict/sequence MAX при exact текущих counters; command_id должен отличаться от latest/active ID. Повтор после освобождения410. Ни автоматического eviction, ни fallback discard при ошибке.

## Immutable attempt до dispatch

Private frozen SaveTarget связывает registry/document/session, исходный command sequence, native revision/position, digest/size/selection. Private frozen CheckpointAttempt: action/control identity/hash, request_id, expected CP/base, immutable current bytes reference, validated CheckpointMetadata(origin=current session/native revision/position), canonical PUT fingerprint, target. Не держать projection/StoredDocx/полный request log.

Все validation/reply shape/resource/counter checks до dispatch; data/metadata codec и fingerprint готовы до первой записи. Под actor mutex публикуется state.active=attempt, editor/sequence/latest прежние. Attempt имеет стабильные UUID/body при каждом retry. Начать новый control/capture/edit при active нельзя; latest accepted native replay остаётся read-only. CommandReceipt action whitelist расширить checkpoint/save (close удаляется и не хранит latest). EditorView.active_command получает detached ActiveCommand(command_id,action,request_sha256,expected_command_sequence,expected_session_revision,stage=checkpoint_pending); state дополнить operation_pending. Ни bytes, ни текст, ни metadata body в descriptor.

PUT вызывается БЕЗ outer SQL transaction. Использовать existing put_checkpoint один owned transaction. Любое исключение после dispatch оставляет active и исходный editor/sequence; не считать exception доказанным rollback. Mutex/semaphore освобождаются между calls, другие документы могут работать. До dispatch failure не создаёт active. Strict unknown/missing input422 и scope-before-expired/conflict прежние.

## Подтверждение/повтор

Actual PUT reply требует working CP=expected+1, last_request_id/fingerprint exact, base/bytes/selection/origin exact target, no pending. Равенства bytes недостаточно. Проверить full target всё ещё принадлежит published editor. При matching current/base приготовить future view/receipt с sequence+1 и CP=reply CP, active=None; native editor/history/saved digest прежние. State publication только после полного reply validation. Если подготовка ответа после SQL commit упала, attempt остаётся для безопасного повторения; БД вручную не откатывать.

Returned current с более новой revision/hash ->409 docx_conflict, active сохранён, false saved ACK нет. Чужой slot/last proof ->409 checkpoint_conflict/idempotency_conflict, не очищать. Fresh CP MAX или command sequence MAX ->409 revision_exhausted до dispatch; release_local исключение, так как actor удаляется без accepted command+1.

Exact control retry latest accepted ID/исходных counters/hash возвращает свежий view без записи/increment; altered action/body/counters ->idempotency_conflict. Exact active retry продолжает прежний PUT, не новый ID. reconcile ссылается на active ID/исходные counters, не создаёт second command/increment; если уже completed latest checkpoint/save — read-only replay. Другой ID/counters stale/idem, отсутствие active/latest control ->409 editor_operation_missing. Completed close actor отсутствует ->410, это не доказательство сохранения/потери.

Snapshot pending классифицирует собственный expected fence/full matching PUT proof read-only; proof в одной transaction. Own unchanged/acknowledged CP + matching current ->operation_pending; foreign head/CP ->conflict. Native latest replay при active может консервативно показать operation_pending до полной сверки; это не recognition по bytes/revision и не подтверждение записи. Никаких nested SQL reads из разных connections с удерживаемым outer lock. Passive proof read не вызывает PUT/reconcile. Last native receipt сохраняется во время active.

Default close готовит ClosedEditor до удаления, после confirmed checkpoint+matching base освобождает actor/open mapping/package budget под index; sequence close резервируется, но новый snapshot удалённой сессии не выдаётся. Ошибка до удаления сохраняет actor/attempt. Поздний прежний open blocked registry open_sequence, даже если release_local ничего не писал. Когда close(mode=checkpoint) ответ потерян после удаления, recovery доступен по durable CP; request retry410.

## Пути и проверки

Разрешены src/ara/docx_editor/**, new frozen tests/acceptance/test_docx_editor_controls.py, дополнительные tests/docx_documents/test_editor_controls_*.py, docs/d03-16d3a-result.md и development-queue.md. D1/D2 tests/native/storage/models/migrations/API/dependencies/runner/tasks/progress/AGENTS не менять. Прежние DTO constructors сохранять default fields, D1/D2 behaviour вне нового active state прежнее.

Freeze/red до кода. Acceptance: exact dirty/selection checkpoint и clean save без current/receipt/history changes; active до первого PUT; ACK-loss before/after commit и DTO failure after SQL commit; immutable retry/full proof/сохранение source tail; no duplicate sequence и superseded/altered IDs; frozen mutations при active, другие документы, full status proof; default close/replay expired/recovery и explicit release_local при conflict/pending/MAX; budget освобождается и stale open не воскрешает actor; scope/error/unknown inputs/inert import; working DB baseline, real PG races/foreign writers, synthetic rich byte reference. Targeted+полный bash scripts/check.sh+result/local commit, затем D3B на Sol 6.1 High автоматически.
