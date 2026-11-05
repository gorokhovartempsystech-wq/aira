# D03-16C3B — explicit pending discard и reconcile

31 октября 2026, после 8277876, Sol 6.1 High, F05/F06/F11/F12. Завершить storage lifecycle pending. Ни UI/таймера/controller mark_saved, ни новых routes/миграций. Discard — только явно вызванная операция, не автоматический fallback после ошибки сохранения.

Новый docx_documents/save_reconcile.py:

- discard_pending(runtime,*,handle:SaveHandle,request_id:UUID)->DiscardedSave.
- reconcile_save(runtime,*,handle:SaveHandle,request_id:UUID)->FinalizedSave.

Input полная cloned/revalidated identity C2 и exact UUID request_id. В reconcile проверить весь input ДО любого commit, чтобы invalid request_id не сохранял документ побочным действием. Same handle/ID повторяем, не изобретать новый operation_id/edits.

Discard под одной `_session`: project→scoped document FOR UPDATE → matching receipt (если есть) → checkpoint. Receipt проверять через C2, включая namespace/metadata; corrupt/foreign receipt даёт безопасный отказ, pending не очищать. Нет receipt — это отсутствие подтверждения, не обещание пользователю «ничего не было сохранено». Current может уже измениться; explicit discard не накладывает старые bytes поверх него.

Checkpoint обязан быть exact pending из handle. Canonical control fingerprint как C3A, action="discard-pending". Использовать _control_state: fresh CAS prepared revision, whole pending match, +1; last matching same/different request ID подтверждает ранее завершённый тот же discard без нового шага. Не узнавать completed по пустому row/bytes без control proof. Новый/чужой checkpoint или другая action ->409 checkpoint_conflict/idempotency_conflict; противоречивый completed proof/result ->500. Fresh MAX ->revision_exhausted, данные остаются.

Fresh discard проверяет legacy как B2B; phase empty, все base/working/metadata поля SQL NULL (JSON null не заменяет SQL NULL), новая checkpoint revision/request/timestamp остаются постоянным tombstone. Current/original/receipts не меняются независимо от наличия подтверждённого save/нового current. DTO готовить до commit, failure откатывает только discard; ACK-loss повторяется по full proof. Старый поздний commit без receipt после discard отклоняется C2, старый matching receipt replay лишь сообщает сохранённый результат без записи.

Новый frozen/slotted DiscardedSave(snapshot:CheckpointSnapshot,handle:SaveHandle,receipt:DocxSummary|None), содержимое repr скрыто. Snapshot checkpoint empty, revision=prepared+1; если receipt есть, validated C2 proof. Properties save_confirmed (receipt is not None), current_matches_receipt (positive confirmation + same storage revision). save_confirmed=false означает «нет подтверждения», не доказанный rollback. Input/output metadata detached.

Reconcile — композиция commit_save и finalize_save с тем же handle/request ID, в разных их собственных transactions, без SQL-lock между requests/operations. Если commit уже произошёл — replay, если finalize уже произошёл тем же handle — completed control proof. Failure между шагами сохраняет durable receipt/pending для следующего повтора; не откатывать current вручную. Чужой head/checkpoint -> прежний конфликт с сохранением данных. Результат current_matches_receipt=false при более новом current не выдавать за актуальную сохранённую рабочую копию в будущем controller.

## Пути и приёмка

Source новый save_reconcile.py; save_models.py только DiscardedSave, прежние DTO/methods не менять. Reuse C2/C3A/checkpoints private helpers, без их редактирования. Старые tests/БД/models/migrations/API/dependencies/runner/tasks/progress/AGENTS не менять. Freeze tests/acceptance/test_docx_save_reconcile.py и этот контракт; дополнительные tests/docx_documents/test_save_reconcile_*.py. Result docs/d03-16c3b-result.md, queue.

Acceptance: explicit discard до/после commit и с более новым current, bytes/ledger прежние; exact/cross-request repeat и tombstone ABA; late commit blocked/receipt replay allowed; no discard finalized/другого checkpoint/action; corrupt receipt refusal; complete reconcile before/after lost response/failure between commit/finalize; invalid input before write; scope/DTO rollback/MAX/fresh process/inert import. Real PostgreSQL concurrency/ACK-loss, baseline, package proof reuse. Red→code→targeted→bash scripts/check.sh→result/local commit. Затем D (runtime controller), E (HTTP/handoff); перед D оценить необходимость отдельного архитектурного review на более мощном режиме, как разрешил Никита.
