# D03-16C3A — finalize и состояние save

31 октября 2026, после 0c1992b, Sol 6.1 High, F05/F06/F11/F12. C3 делится на A (status/finalize) и B (discard_pending/reconcile). Очистить pending только после подтверждённого matching receipt, без изменения Word bytes/current/ledger. Controller mark_saved остаётся D.

Новый docx_documents/save_finalize.py:

- get_save_status(runtime,*,handle:SaveHandle)->SaveStatus, read-only под project→scoped document FOR SHARE.
- finalize_save(runtime,*,handle:SaveHandle,request_id:UUID)->FinalizedSave, под project→scoped document FOR UPDATE.

Input handle clone/revalidate через C2, request_id exact UUID. Safe invalid input 422. SaveStatus frozen/slotted: state (ready/conflict/exhausted/committed/committed_outdated/superseded), document:StoredDocx, handle:SaveHandle, receipt:DocxSummary|None, checkpoint_revision:int|None. Скрыть содержимое из repr. При receipt использовать C2 _committed для полной проверки и не читать checkpoint/legacy; state committed, если current совпадает с receipt revision, иначе committed_outdated. checkpoint_revision тогда None. Наличие receipt не доказывает cleanup/принадлежность нового checkpoint этому окну.

Без receipt проверить checkpoint/legacy как B2B. Matching pending+current base ->ready; если counters исчерпаны ->exhausted. Matching pending с чужим current ->conflict; отсутствующий/другой checkpoint ->superseded. Учитывать revision вместе с hash, без догадок по одинаковым bytes. Stored corruption/unknown schema ->500 без очистки. Статус не создаёт empty slot и ничего не записывает.

## Finalize и повторы

Под lock проверить scope/current и matching receipt C2. Receipt нет ->409 save_unconfirmed, никаких изменений. Target pending должен точно соответствовать full handle. Fresh finalize при current!=receipt ->409 docx_conflict, pending остаётся. Успех: phase working, base revision/hash из receipt, прежние working bytes/selection/origin, metadata.pending=null; checkpoint revision+1, timestamp/last request. Original/current/receipt ledger не менять.

Control fingerprint: тот же checkpoint namespace v1, canonical JSON {version:1,action:"finalize",document_id,expected_checkpoint_revision:handle.prepared_checkpoint_revision,request_id,operation_id,save_request_sha256}; UUID/revisions strings. Full handle до этого пересчитан/проверен, save_request_sha256 связывает все его поля.

Если row revision=prepared+1 и last_request_id совпадает с request_id, wrong fingerprint ->409 idempotency_conflict; exact -> completed только после проверки целого working result. Если request_id другой, можно распознать уже завершённый тот же finalize: пересчитать control fingerprint с row.last_request_id и full handle, проверить phase/base/candidate/selection/origin. Тогда вернуть подтверждение без новой записи/смены last request (два восстанавливающих окна могут завершать одну операцию). Нельзя объявить completed по одним bytes/hash. Другой checkpoint revision/request/action ->409 checkpoint_conflict. Фиктивно matching control proof при противоречащих stored fields ->500 storage_error.

FinalizedSave frozen/slotted {snapshot:CheckpointSnapshot,receipt:DocxSummary,handle:SaveHandle}; свойства current_matches_receipt как C2. DTO проверяет рабочий checkpoint revision=prepared+1, base=receipt, exact candidate/selection/origin и pending=None, используя C2 proof. При completed replay current может уже быть новее; ответ показывает это отдельно, не меняет checkpoint/current и не даёт основания выставить актуальный clean в controller. Fresh finalize требует текущий head==receipt. Reply validation внутри transaction, ACK-loss повторяем той же identity; Returned/caller metadata detached.

## Резерв revision для завершения

Найдено при подготовке cleanup: C1 ранее мог занять последнюю checkpoint revision, после чего finalize +1 невозможен. Fresh prepare теперь требует expected checkpoint revision≤MAX−2; при MAX−1/MAX ->409 revision_exhausted без создания pending. Fresh C2 commit отказывает, если prepared checkpoint revision=MAX (legacy/external staged state), до записи current/receipt. Existing prepare/commit receipt replay на границе остаётся разрешён: не прятать уже состоявшееся сохранение. Старое exhausted pending сохраняется/readable/exportable; счетчик не обнуляется.

Эта узкая поправка дополняет технические границы прежних C1/C2 и сохраняет их positive/replay/invalid tests; не ослаблять frozen assertions. C1/C2 исходные record классы/семантика остальных случаев не меняются. get_save_status matching exhausted pending сообщает exhausted вместо ready.

## Пути и приёмка

Source новый save_finalize.py; save_models.py только SaveStatus/FinalizedSave; save_prepare.py/save_commit.py только описанные fresh counter guards. Старые classes/tests/checkpoints/recovery/БД/schema/HTTP/dependencies/runner/tasks/progress/AGENTS не менять. Freeze tests/acceptance/test_docx_save_finalize.py, этот контракт, датированные reserve notes в C1/C2 contracts. Дополнительные tests/docx_documents/test_save_finalize_*.py. Result docs/d03-16c3a-result.md, queue.

Acceptance: status ready→committed→finalized, clean restore и сохранность working/selection; before-confirmation отказ; foreign current даже same bytes; repeat/same and different request ID/concurrent cleanup/altered identity/superseded slot; no cleanup другой action/чужой версии; DTO rollback/ACK-loss; counter reservation/MAX legacy readable; scope/corruption; restart; import inert. Real PostgreSQL, baseline, exact package proof reuse. Red→code→targeted→bash scripts/check.sh→result/local commit; затем C3B автоматически на том же режиме.
