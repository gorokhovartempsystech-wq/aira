# D03-16D1 — ограниченный контракт реализации registry и открытия

31 октября 2026, Astra 6 High. Техническое основание d03-16d-design.md §§1–4,7,9; F05/F11/F12. Реализация на Sol 6.1 High. Этот контракт фиксируется до новых acceptance tests и исходников; не означает, что D1 выполнен.

## Пути

- Новые `src/ara/docx_editor/__init__.py`, `_models.py`, `_registry.py`, `_scope.py`, `_recovery.py`, `_budget.py`. Дополнительные private файлы внутри этого пакета допустимы только для D1 responsibilities.
- `src/ara/docx_package/session/_session.py` — только `_retained_packages()` returning `(state.data, *state.undo, *state.redo)`; `src/ara/docx_package/editor/_session.py` — только forwarding `_retained_packages()`. Прежние методы/конструкторы не менять.
- Новая frozen acceptance `tests/acceptance/test_docx_editor_registry.py`, дополнительные `tests/docx_documents/test_editor_registry_*.py` (существующий testpaths подхватит их). Docs d03-16d1-result.md и development-queue.md.
- Никаких edits commands/save/close methods, HTTP/routes/app wiring, DocumentRuntime/model/migration changes, старых tests, зависимостей, runner/tasks/progress/AGENTS. B/C helpers только читать/вызывать, не менять. Не добавлять поля existing DTO.

## Python API и records

`from ara.docx_editor import EditorRegistry, RegistryLimits`.

- `EditorRegistry(runtime, *, limits=None)` explicit constructor; exact DocumentRuntime, повторная validation frozen-bypass fields, owned copy (engine reference shared); default limits либо exact validated RegistryLimits. Конструирование не использует engine и не создаёт соединений/файлов/секретов. New registry UUID, sequence0, no actors.
- `inspect_recovery(*, document_id: UUID) -> RecoveryView`.
- `open(*, document_id: UUID, registry_id: UUID, client_open_id: UUID, expected_open_sequence: int, expected_checkpoint_revision: int, mode: str) -> OpenedEditor`.
- `snapshot(*, document_id: UUID, session_id: UUID) -> EditorView`.

RegistryLimits(max_sessions=8, max_retained_bytes=268435456), exact positive ints без bool. Methods не принимают runtime/user/project/bytes/editor или увеличенные native limits. Budget counters доступны тестам через private state без обещания public metrics API.

Все новые DTO frozen/slotted, strict validation, nested fields и payload-bearing repr скрыты; копии caller records не становятся mutable authority. Output не содержит сам EditorSession, SQL row/Session/Engine или raw request. Native EditorSnapshot содержит bytes как Python DTO; запрещено обещать его прямую JSON serialization.

RecoveryView: registry_id UUID, open_sequence int0..MAX, document DocxSummary, checkpoint_revision int0..MAX, phase absent/empty/working/pending; base_storage_revision/base_sha256/working_sha256/working_size_bytes, selection, origin nullable; pending_status nullable SaveStatus.state, operation_id nullable UUID. absent iff revision0; absent/empty не содержат working/base/selection/origin/pending; working не содержит pending fields; pending содержит классификацию и op ID. DOCX bytes в RecoveryView нет. Если stored checkpoint есть, base/selection/origin проходят уже существующие codecs. Есть receipt — получить current_matches через C2 validation в том же transaction; отсутствует — ready/conflict/exhausted по C3A правилам. Scope before classification.

EditorView: registry_id/document_id/session_id UUID, command_sequence0 для D1, editor EditorSnapshot, base_storage_revision int1..MAX, base_sha256 hex64, checkpoint_revision int1..MAX (captured actor fence), observed_current DocxSummary, observed_checkpoint_revision int0..MAX, observed_checkpoint_phase absent/empty/working/pending, state editable/recovery_pending/conflict. `last_command` и `active_command` отсутствуют в D1 API, добавляются точным D2/D3 контрактом. `recovery_operation_id` UUID|None показывает наличие восстановленного pending. Full SaveHandle только private actor, не arbitrary writable client payload. Native is_dirty/history/counters проверяются; doc IDs согласованы.

OpenedEditor: view EditorView, accepted_open_sequence int0..MAX−1 (исходный expected), next_open_sequence int1..MAX (registry sequence на момент reply). Повтор может вернуть новый next_open_sequence и свежую observed_current, но same session/editor history/identity.

Strict input errors -> DocumentError422 validation_error. Scope/notfound404; unknown registry410 editor_registry_expired; unknown/closed session410 editor_session_expired; fresh expected_open_sequence mismatch409 stale_open; altered live client ID409 idempotency_conflict; mode/CP mismatch409 checkpoint_conflict; MAX fresh open409 revision_exhausted; admission413 editor_limit_exceeded. Stored errors503/500 через существующую safe boundary. Valid package без поддерживаемой body selection ->422 editor_document_unsupported (файл не теряется), не «повреждённый stored DOCX». Generic внутренние DTO failures ->500 editor_error, sanitized. No contents in messages/logs.

## Storage observation

`_recovery.py` выполняет passive согласованный read под `_session`/`_document(read=True)`, `_snapshot`/`_record`/`_legacy`; receipt verification `_committed` в том же transaction. Это новый adapter, не wrapper, вызывающий several transactions. При absent не INSERT. Использовать B/C canonical helpers, не упрощённую собственную проверку stored metadata.

Fresh open обычно строится из этого read. Для absent/expected0 initialization вызывается отдельно существующим get_checkpoint без outer SQL transaction. Пригоден только returned empty1 с NULL last request. Другие revision/phase ->409. Initial empty может остаться после последующего resource/DTO failure; current/working не меняются. Repeated get не увеличивает CP. Foreign document и legacy draft не получают нового actor/slot. Для already existing revision требуется exact observed match.

Snapshot/live-open retry `_scope.py`: Project FOR SHARE и scoped Document summary FOR SHARE, плюс checkpoint fence в этом transaction, без BLOB чтения. Перед expired/conflict/error на cached actor проверять scope. Повтор после ожидания actor mutex снова проверяет доступ. Caller не может узнать session чужого document по различию expired/replay errors.

Исключение для recovered pending: нужен повторный passive full proof read из `_recovery.py` в одной transaction. Matching handle + verified receipt/current определяет recovery_pending/conflict; changed slot даёт conflict с сохранением old private handle. Нельзя считать факт save подтверждённым по одним hash/revision. Тест отсутствия BLOB у cached path относится к обычному current/working actor; pending proof закономерно читает package.

## Открытие/восстановление

current разрешён empty/absent; clean0/position0/undo0/redo0. recover working/pending exact bytes/selection с saved_sha=base, новая epoch, revision0/position0/history0. Исторический origin не копируется в local counters. Working base!=current -> conflict actor; pending matching base/receipt -> recovery_pending, pending foreign current -> conflict. Pending corrupt receipt -> safe refusal, не actor и не cleanup. При pending matching receipt редактор остаётся frozen до будущего reconcile; не делать mark_saved/auto commit/finalize в open.

Разные client_open_id могут создать два actors одного документа (в пределах лимита) последовательно с новым open_sequence. Один client_open_id — один live actor по registry, altered document/mode/expected values conflict после scope check. Admission и reply готовятся до index insertion и sequence increment. Две concurrent копии одного open возвращают один session/один increment; разные opens на одной sequence: один accepted, другой stale_open, без утечки reservation. Replay не зависит от текущей sequence и остаётся доступным при capacity/MAX; новые admissions запрещены. Все actor scopes принадлежат constructor runtime.

Registry restart выдаёт новый registry ID; старый open/session не продолжает RAM автоматически. Recovery нового registry строит новую session с пустой history и сохранёнными working bytes. D1 close не предоставляет: bounded lifetime registry заканчивается с приложением; production wiring ждёт D3. Не добавлять unsafe temporary remove/public mutable actor для тестов.

## Retained и locks

Считать actual immutable bytes references, union actors+candidate reservation. Не retain SQL original/current, если они не editor current/history; не retain projection между requests. Поддержать registry budget ниже одного пакета — явный413 с освобождением slots. Содержимое двух разных bytes objects считается дважды. Равный id учитывается один раз с удержанием ссылки. New retained helper не меняет историю и не вызывает I/O.

Lock protocol — §4 дизайна: open mutex, actor mutex перед heavy semaphore, краткий index lock; без ожидания/SQL внутри index и без ожидания RAM locks в transaction. Scope/read failure до публикации не оставляет actor/sequence/mapping/reservation. Свойство native `_retained_packages()` проверить на существующем EditorSession после нескольких edits/undo/redo, хотя registry commands ещё не включены.

## Frozen acceptance перед реализацией

Написать и локально зафиксировать acceptance ДО source, получить red на отсутствии нового API. Тестовые документы синтетические, real PostgreSQL disposable DB; рабочую ara_dev не мигрировать. Обязательные проверяемые сценарии:

1. Passive inspect absent без записи; new current open exact bytes/clean; repeat одного client ID, другой actor, strict current/recover modes и CP CAS.
2. Dirty working restore exact bytes/направление selection, origin не active epoch, история пуста; clean working не становится dirty; read-only conflict copy при foreign base.
3. Pending до commit и после receipt открывается frozen без изменения current/CP/receipt, новый session ID; corrupt/foreign receipt безопасно отказывает, slot сохранён.
4. New registry и отдельный процесс дают новые IDs; старый registry open410, старый session410 при own document, foreign404. Нет false saved при recovery.
5. Две threads с одним open и с разными opens на одной sequence; один increment/actor, bounded retry без reset. MAX допускает replay/snapshot, запрещает fresh open.
6. Same client ID altered document/mode/counters ->idem conflict, old open без live mapping ->stale, без создания actor. Не менять существующие frozen tests ради новых errors.
7. Revocation project owner/document scope после открытия блокирует snapshot/replay; SQL trace подтверждает отсутствие BLOB на cached scope query. Не смешивать чужие данные с conflict errors.
8. Limit count/bytes, union reference accounting current+undo+redo+candidates; exact boundary, отказ без eviction, освобождение при package/DTO/SQL commit failure и повтор успешного open после устранения fault.
9. Input/output detachment, tampered frozen DTO/limits, bool/negative/overflow/unknown input, no secrets/text in diagnostics, inert first import/constructor.
10. Original/current/receipt/legacy сохранность; baseline до/после, targeted, полный bash scripts/check.sh. После gate result/local commit. Далее D2 автоматически на Sol 6.1 High по отдельному контракту.
