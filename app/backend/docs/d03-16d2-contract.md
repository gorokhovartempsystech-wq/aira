# D03-16D2 — последовательные native команды live editor

31 октября 2026, после 841af09, Sol 6.1 High. F05/F11/F12, d03-16d-design.md §§3–5,7. Подключить existing native intents к D1 registry. Без durable writes, HTTP, save/checkpoint/close, timers или frontend. Рабочая БД не мигрируется.

## API и validation

Новый exported frozen/slotted `EditorCommand(action: str, value: object = None, after: SelectionTarget | None = None)`; payload repr скрыт. Это tagged union с exact правилами, не произвольный method dispatch:

| action | value | after |
|---|---|---|
| capture | exact EditorSelection | None |
| insert_text | str ≤100000 code points, прежний typing limit | None |
| paste_text | str ≤1M code points | None |
| enter, join_previous, join_next, insert_soft_break, undo, redo | None | None |
| range_edit | tuple[RangeEdit,...], 0..1000 | exact SelectionTarget, обязательно |
| structure | tuple[InsertParagraph|DeleteParagraph,...], 0..1000 | exact SelectionTarget, обязательно |
| format | tuple[ParagraphFormat,...], 0..1000 | SelectionTarget или None |

Constructing command validates/detaches input; command request повторно normalizes даже frozen-bypass objects. Никаких arbitrary classes/callables/списков вместо tuples/неизвестных fields/limits. Все поля allowlisted native records revalidate; clone только после bounded structural checks. Native strings и replacement получают прежнюю XML/code-point validation. Expected text и replacement/texts ограничены каждый суммарно 1M chars на request; максимум новых paragraphs1000. Это технический memory/transport bound, не продуктовый предел документа.

SourceAnchor part 1..1024 chars без NUL/surrogates; path exact tuple1..128, indices0..100000; offsets и target block_index0..2^31−1. Строки сначала length/type, затем semantic validator; не обходить гигантский невалидный tuple/string до budget check. Existing ParagraphFormat style/list constraints прежние. Stale source/selection и unsupported semantics проверяет native editor на текущем пакете. Caller не может дать новый DOCX/EditorSession/operation callable.

`registry.command(*, document_id:UUID, session_id:UUID, command_id:UUID, expected_command_sequence:int, expected_session_revision:int, command:EditorCommand)->EditorView`. UUID exact, counters0..MAX strict без bool. Новые EditorView поля `last_command:CommandReceipt|None` и `active_command:None` с defaults сохраняют D1 constructors. CommandReceipt frozen/slotted: command_id, request_sha256, action, expected_command_sequence, expected_session_revision, result_command_sequence, result_session_revision, result_position_id. Без текста/projection. В D2 command_sequence уже0..MAX; active pending добавится D3. Пустые latest/active на open.

Fingerprint namespace ara.docx.editor-command.v1\0, canonical payload по d03-16d-design: IDs/counters/action/value/after; UUID и 64-bit counters strings; explicit allowlisted record serialization, sort_keys/ensure_ascii/separators compact; streaming iterencode→SHA без giant JSON string. Не generic asdict arbitrary objects. Canonical tuple sequences wire lists. Storing latest proof не удерживает input text/value/after.

## Порядок и публикация

Scope before session existence/conflict/replay. Actor mutex→heavy semaphore→metadata-only scoped read transaction. No SQL writes. Pending recovered actor ->409 editor_operation_pending; foreign storage/CP fence ->409 docx_conflict/checkpoint_conflict, RAM остаётся доступной через snapshot. Latest exact command replay при этом разрешён: возвращает accepted identity + свежий view, в том числе conflict, без повторной операции. Другой command ID с неверными expected counters ->409 stale_command. Тот же latest ID с altered body/counters ->409 idempotency_conflict. Старый superseded ID не хранится навечно; прежние counters дают stale_command.

Fresh request требует оба exact current counters, sequence<MAX; потенциально изменяющие bytes/history actions требуют native revision<MAX (даже no-op); capture может при core MAX. Copy trusted EditorSession, execute explicit action mapping с defaults limits, snapshot/reply complete и counter/position validation, reservation union live+candidate. Успешный capture/no-op ->sequence+1 без обязательного native revision increment. Pure errors/DTO/resource/read commit failure не меняют editor/history/selection/sequence/latest proof, reservation освобождена. После успешного выхода read transaction один published state assignment включает editor+sequence+latest receipt; бюджет переводится вместе с ним.

Для этого разрешён private `_ActorState` frozen/slotted внутри registry: editor/base/CP/handle/sequence/latest. Actor содержит mutex/session/document/open request и ссылку на state. D1 behaviour/DTO constructors/public methods сохраняются; native source вообще не менять в D2. Snapshot не cache-ит projection/SQL row/StoredDocx. New command не пишет checkpoint/current/receipt. Open replay возвращает текущее состояние actor, не initial view.

Ошибки native Editor/Session/Range/Structure/Formatting/Boundary/Docx/Projection преобразуются в DocumentError: limit_exceeded413, stale_revision409 stale_command, остальные422 с прежним code/message. Конфликты registry409. Input-shape422 validation_error, overflow409 revision_exhausted, unknown internal/DTO500 editor_error, SQL503/500 прежние. Native failures внутри `_session` переводить до общего storage catch. First import inert; module/constructor не читают секреты/сеть/БД.

## Пути и приёмка

Разрешены src/ara/docx_editor/**, new frozen tests/acceptance/test_docx_editor_commands.py, дополнительные tests/docx_documents/test_editor_commands_*.py, docs/d03-16d2-result.md и development-queue.md. Не менять old D1 acceptance/tests, pure editor/session/range/structure/formatting source, schema/migrations/storage/API/dependencies/runner/tasks/progress/AGENTS.

Acceptance freeze до source/red: все actions через public command; exact native bytes/selection/history, undo/redo; capture/no-op ordering; same retry/altered latest/superseded/parallel requests; pending/base/CP conflict и scope before errors; candidate/reply/read commit failure с rollback RAM; union budget включая dropped-history старого live; MAX, strict DTO tampering/callable/unknown inputs, Unicode/paste и counters; latest proof без текста, output isolation, inert import, original/current/CP/SQL receipts неизменны. Real PostgreSQL, separate process epoch из D1, synthetic rich visual byte proof reuse/контроль native edits. Targeted + полный bash scripts/check.sh + result/local commit, затем D3A автоматически на Sol 6.1 High.
