# D03-16E1 — pure wire codec редактора

31 октября 2026, после b219585, Sol 6.1 High. F05/F06/F11/F12. Первый transport-подцикл: strict native request mapping и bounded явная serialization. Никаких routes/app wiring/runtime/storage/native behaviour changes. Следующие E2 (JSON routes/lifetime) и E3 (binary recovery/handoff/deadlines) получают отдельные контракты.

## Уточнение transport решения

Ответы mutating/open/control HTTP будут небольшими metadata replies; полная structural projection получается отдельным read-only GET session view. Это уточняет набросок transport d03-16-design.md без изменения продукта: неудача сериализации большого view не делает обычный ACK сохранения/команды недоступным. Snapshot metadata содержит dirty/history/selection/counters/last/active, но не DOCX/text/projection tree. Отдельный full-view ответ связывает metadata и projection одного EditorView, без второго GET latest. Никакого обрезания или выдачи opaque объектов за полноценный Word render.

Binary DOCX — отдельный будущий endpoint. Source._original/DocxSource/StoredDocx/SavedTarget.data никогда не сериализовать в JSON. E1 не меняет состояние registry и не вызывает БД.

## API `ara.docx_editor.wire`

- decode_open(value:dict)->dict kwargs registry.open без document_id: exact keys registry_id/client_open_id/expected_open_sequence/expected_checkpoint_revision/mode. UUID canonical lowercase strings→UUID, counters canonical decimal strings0..MAX→int, mode current/recover.
- decode_command(value:dict)->dict kwargs registry.command без document_id/session_id: exact keys command_id/expected_command_sequence/expected_session_revision/command. command dict с обязательным action, optional value/after; неизвестных ключей нет. Отсутствующее value/after равно None. Проверенные native DTO EditorCommand.
- decode_control(value:dict,*,close=False)->dict kwargs control без path IDs. Первые три identity поля command envelope; при close допускается optional mode default checkpoint, только checkpoint/release_local. Без close mode запрещён. saved_target getter использует тот же identity shape и counters результата по D3B, не особый более слабый decoder.
- encode_reply(value:RecoveryView|OpenedEditor|EditorView|ClosedEditor)->bytes UTF-8 JSON, ≤65536 bytes.
- encode_projection(value:EditorView)->bytes UTF-8 JSON `{kind:editor_projection,view:<metadata>,projection:<structural tree>}`, ≤8MiB. Оба из одного detached EditorView. Structural budget как прежний view transport: ≤5000 dataclass records, ≤1M string code points, depth≤128; отказ413, без truncation. Это технические wire пределы, не утверждение о готовности всех DOCX возможностей.

Чистый codec не читает env/файлы/сеть/engine при импорте/вызове. Raw JSON bytes/media/duplicate key/stream/header проверка будет в E2. Здесь exact Python dict/list/primitive validation, no coercion или generic dataclass conversion. Unknown/invalid input422 validation_error; invalid internal DTO500 editor_error; output budget413 editor_reply_limit_exceeded.

## Command JSON

Все anchors: exact `{source_sha256,part_name,path}` с прежними bounded hash/part/path rules; path JSON list→tuple только после length/type check. Caret `{anchor,offset,affinity?}` default right; Selection `{anchor,focus}`. SelectionTarget тот же shape, но caret `{block_index,offset,affinity?}`. Offsets/path indices JSON ints без bool, code points, не UTF-16; native after constraints D2 прежние.

range_edit.value — JSON list ≤1000 exact `{start:{anchor,offset},end:{anchor,offset},expected_text,replacement_text}`. structure.value — list exact `{kind:insert,anchor,expected_text,texts?,position?}` defaults texts=[empty], position=after, либо `{kind:delete,anchor,expected_text}`. format.value — list exact `{anchor,expected_text,style_id?,list_kind?,list_id?}` defaults None/none/None. capture.value — Selection; typing/paste.value — str; прочие value=None. Native validators и агрегатные D2 text/new paragraphs caps сохраняются, bound до создания/копирования/хеша. No arbitrary methods/kwargs/limits/bytes.

## Ответы

`kind` — recovery/opened/editor/closed. IDs lowercase UUID strings. Все 64-bit revisions/sequence/position strings (в том числе last/active/origin), offsets/history depths/size bytes безопасные ints. Datetime summary ISO8601 aware strings. Обычные bool/None остаются JSON bool/null.

Opened: kind, view, accepted_open_sequence, next_open_sequence. Closed: kind, registry_id/document_id/session_id/mode/checkpoint_revision nullable. Recovery: все одноимённые RecoveryView поля, document summary явно по полям; selection/origin typed maps.

Editor: registry_id/document_id/session_id/command_sequence/base_storage_revision/base_sha256/checkpoint_revision/observed_current/observed_checkpoint_revision/observed_checkpoint_phase/state/recovery_operation_id/last_command/active_command/position_id/selection; `document` metadata = session_revision/source_sha256/main_part/size_bytes/is_dirty/undo_depth/redo_depth. Ни document.data, ни blocks, ни text. Last/active поля — те же публичные records, вручную; source IDs и counters сохраняются.

Projection: source_sha256/main_part/body_anchor/coverage_scope/has_unprojected_content/blocks/notices. Явные whitelists полей native SourceAnchor/Hyperlink/Span/Paragraph/OpaqueBlock/Cell/Row/Table/Notice; tuple→list. Не использовать asdict(Source)/generic fallback. Opaque/notices передаются, не скрываются. Payload-bearing repr/errors не раскрывают текст/пароль/SQL.

## Пути/приёмка

Только новый src/ara/docx_editor/wire.py и при необходимости private _wire_*.py, frozen tests/acceptance/test_docx_editor_wire.py, дополнительные tests/docx_documents/test_editor_wire_*.py, result docs/d03-16e1-result.md и queue. Никаких old source/tests/DTO/schema/API/runner/tasks/progress/dependencies changes. Freeze/red до source.

Acceptance: все command families→exact native types/defaults; canonical UUID/64-bit MAX/reject bool/float/coercion/leading zeros/unknown keys; nested tampering/shape/size before copy; native unsupported errors unchanged; all reply kinds metadata без bytes/text; direction/affinity/counters exact; full rich projection main-body content/opaque/notices, no source package; output nodes/text/size/depth refusal without truncation; unknown DTO rejection, input/output isolation/inert import/no DB. Targeted+общий bash scripts/check.sh→result/local commit, затем E2 на Sol 6.1 High.
