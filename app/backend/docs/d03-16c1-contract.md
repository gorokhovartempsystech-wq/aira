# D03-16C1 — immutable prepare-save

31 октября 2026, после eee1a22, Sol 6.1 High, F05/F06/F11/F12. Первый подцикл прежнего C. Подготовить durable pending save и полную проверяемую identity; current/original/receipts не изменять. Commit — C2, finalize/discard_pending — C3. Без новых HTTP/routes/миграций/таймера/UI.

API ara.docx_documents.save_prepare.prepare_save(runtime,*,document_id:UUID,expected_checkpoint_revision:int,request_id:UUID,operation_id:UUID,base_storage_revision:int,base_sha256:str,data:bytes,metadata:CheckpointMetadata)->PreparedSave. Metadata на входе working (pending=None); default budgets/strict validation и безопасные ошибки как B2B.

Один project→document lock/_session. Reuse B2B scope/legacy/record/retry helpers. Slot существует после get. Prepare fingerprint использует тот же checkpoint namespace v1, action=prepare, все поля put (с готовой pending metadata) плюс operation_id string. Для точного replay при expected+1/last request вернуть прежний pending/result, включая случай более нового current; не менять timestamp/revision. Altered fingerprint ->idempotency_conflict, superseded ->checkpoint_conflict, чужой pending ->pending_save_required. Fresh transition при MAX checkpoint/base storage revision запрещён revision_exhausted.

Fresh prepare проверяет отсутствие operation_id в общем DocxEditReceipt до записи (409 idempotency_conflict при коллизии с прежним save), exact current base revision/hash и отсутствие legacy. Вычислить future prepared revision=expected+1 и save fingerprint по рецепту d03-16-design.md. Записать phase=pending, точные working bytes/hash/base/selection/origin, pending {operation_id,request_sha256}, новую checkpoint revision/last request/update. Candidate только в checkpoint, original/current/receipt ledger неизменны. DTO/reply failure откатывает transaction; uncertain ACK повторяет прежний request/operation ID.

## Полная identity и уточнение дизайна

Новый frozen/slotted SaveHandle в save_models.py: document_id UUID, prepared_checkpoint_revision int, base_storage_revision int, base_sha256 str, working_sha256 str, working_size_bytes int, metadata CheckpointMetadata (pending обязателен). Properties operation_id/request_sha256 берутся из metadata.pending. Bounds/формы/тип exact/frozen bypass проверить; source hashes обеих selection точек равны working_sha256. Metadata repr скрыть. Constructor ошибочной identity ->ValueError с безопасным сообщением.

SaveHandle содержит полный canonical payload для пересчёта request_sha256 без DOCX bytes. Это уточнение минимального handle из проектного документа: после очистки checkpoint у старого replay остаётся receipt, и одна переданная hash-строка не позволяет проверить изменение prepared revision/других полей handle. Полная identity связывает все поля с receipt fingerprint и позволяет C2 проверить receipt revision=base+1/candidate digest/size после supersession. Это техническое усиление прежней immutable identity, без нового бизнес-правила/схемы БД.

PreparedSave(snapshot:CheckpointSnapshot,handle:SaveHandle), frozen/slotted, скрыть snapshot/metadata из repr. Handle и snapshot не разделяют изменяемые metadata/anchors. Подготовить/проверить reply внутри transaction. Оба относятся к тем же pending bytes/revision/base; snapshot.document может быть новее base при replay и не доказывает актуальность pending.

Новый save_identity_fingerprint(document_id,revision,base_revision,base_sha256,working_sha256,working_size_bytes,metadata_wire) использует прежний save namespace/recipe. pending_fingerprint делегирует ему с digest/size actual data — старые результаты неизменны. Checkpoint fingerprint получает опциональный operation_id, branch prepare добавляет data/metadata как put и operation_id. Старые put/discard результаты и их tests сохраняются.

## Пути и приёмка

Source новые docx_documents/save_models.py/save_prepare.py; checkpoint_fingerprints.py только описанное расширение/refactor с прежним результатом. Checkpoints.py/recovery.py/БД/DTO/старые tests/dependencies/runner/tasks/progress/AGENTS не менять. Freeze tests/acceptance/test_docx_save_prepare.py и этот контракт, уточнение docs/d03-16-design.md. Дополнительно tests/docx_documents/test_save_prepare_*.py. Result docs/d03-16c1-result.md и queue.

Acceptance: empty/working→pending exact bytes/selection, сохранённый document/ledger прежние; prepare replay/mismatch/superseded/other pending; old key collision; stale base/scope/MAX; proof fingerprint independently matches canonical recipe and detects changed handle after checkpoint removal; DTO/metadata isolation; transaction/reply/ACK-loss/new engine/process; stored corruption и import/no I/O. Red→code→targeted→bash scripts/check.sh→baseline→report/local commit. Затем C2 на том же режиме, если нет новой архитектурной неоднозначности.

Уточнение 31 октября в C3A: fresh prepare резервирует ещё одну checkpoint revision для finalize, поэтому MAX−1 также отказывает revision_exhausted. Старый matching prepare replay сохранён. Обнаруженный крайний случай и regression acceptance описаны в d03-16c3a-contract.md; прежние frozen проверки не изменяются.
