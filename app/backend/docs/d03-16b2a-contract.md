# D03-16B2A — чистый формат metadata checkpoint

31 октября 2026, после d80e246, Sol 6.1 High, F05/F11/F12. Узкий первый подцикл прежнего B2. Строго кодировать/декодировать metadata новой таблицы; SQL CAS/legacy arbitration остаются B2B, проверка pending receipt/fingerprint в контексте всей строки — C. Не считать валидную форму hash доказательством сохранения.

Новый pure модуль ara.docx_package.checkpoint, без зависимости от SQLAlchemy/Pydantic/runtime. API frozen/slotted records:

- CheckpointOrigin(session_id:UUID,session_revision:int,position_id:int).
- PendingSave(operation_id:UUID,request_sha256:str).
- CheckpointMetadata(selection:EditorSelection,origin:CheckpointOrigin,pending:PendingSave|None=None), repr скрывает поля.
- CheckpointError с безопасными code/message invalid_input и checkpoint_limit_exceeded.
- encode_metadata(value:CheckpointMetadata,*,data:bytes,saved_sha256:str,phase:str)->dict.
- decode_metadata(value:dict,*,data:bytes,saved_sha256:str,phase:str)->CheckpointMetadata.

Обе функции перепроверяют type exact/frozen bypass, package/projection/default history limits через EditorSession.restore и сохранённый digest согласно A. Возвращают detached JSON/DTO, не удерживают DOCX/projection/caller DTO. Existing package/editor/session errors допустимы без содержимого; ошибки формы codec -> CheckpointError invalid_input.

Wire object exact keys {selection,origin,pending}. selection exact {anchor,focus}; каждая точка {anchor,offset,affinity}; source anchor {source_sha256,part_name,path}. Источник должен совпадать с реальным working package, main part/body p/offset проверяется restore. UUID в JSON — lowercase canonical string, в records — настоящий UUID. origin revision/position в JSON — canonical unsigned decimal strings 0…2^63−1 (без leading zero кроме 0); в records строгие int без bool. Поля part_name 1…1024 chars, path list wire/tuple DTO длиной 1…128, компоненты int 0…100000, offset int 0…2^31−1, affinity exact left/right; hash настоящий str hex64 lowercase. Формат значения не исправлять автоматически.

pending JSON null для phase=working; exact {operation_id,request_sha256} для phase=pending. Другие phase, включая empty, отклоняются (empty row вообще не имеет metadata). Origin — историческая identity; decode не восстанавливает session ID живого controller. Pending hash здесь проверяется только по форме: сопоставление с save fingerprint/receipt требует document ID/revisions строки и будет в C.

Canonical UTF-8 JSON (sort_keys,ensure_ascii=True,compact separators) ≤65536 bytes. Дополнительно bound JSON text с обычными separator spaces/ensure_ascii=False, чтобы не выходить за SQL JSONB::text gate B1. Сначала проверить фиксированную форму и границы полей, только затем сериализовать; giant unknown fields/cycles/deep lists/invalid surrogate или NUL не должны вызвать recursion/memory amplification и не логируются. Ни чтения env/secrets/files/network, ни процессов/БД при import/первом вызове.

Freeze acceptance tests/acceptance/test_docx_checkpoint_metadata.py. Source только новый checkpoint/__init__.py и при необходимости его private modules; старые exporters/DTO/restore/БД/API/dependencies/tests не менять. Дополнительные tests/docx_session/test_checkpoint_metadata_*.py. Результат docs/d03-16b2a-result.md и queue update. Red→implementation→targeted→bash scripts/check.sh→DB baseline→local commit, затем B2B автоматически, если режим достаточен.

Acceptance: exact clean/dirty JSON roundtrip с Unicode selection и reverse affinity; pending shape/phase; origin revision 0/max без float coercion; uuid/hash strict; missing/unknown/nested/boolean/null/negative/overflow/mutated inputs; foreign anchor/main part/outside text и повреждённый package; вход/выход не разделяют mutable anchors/lists; first import/call inert. Не доказывать durable storage этими pure тестами и не создавать DOCX artifacts ради schema codec.
