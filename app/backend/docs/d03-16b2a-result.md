# D03-16B2A — строгий формат metadata checkpoint

31 октября 2026, Sol 6.1 High. Выполнен d03-16b2a-contract.md. Новый pure ara.docx_package.checkpoint: CheckpointOrigin/PendingSave/CheckpointMetadata и encode_metadata/decode_metadata. Exact nested JSON schema, канонические UUID/revision strings, строгие типы без bool/coercion, phase working/pending, bounded path/offset/part/digest. Selection проверяется по настоящим working bytes через restore A; saved digest сам по себе не подтверждает запись в storage.

Входная форма ограничивается до JSON-сериализации, циклы/глубокие структуры/гигантские unknown fields/invalid Unicode не приводят к рекурсивной сериализации. Проверяется canonical UTF-8 JSON и JSON text bound SQL B1. Выходы detached; frozen bypass перепроверяется. Модуль не хранит DOCX/projection и не читает env/files/network/БД, не запускает процессы/логирование при первом импорте/вызове.

Freeze **649688c**, red **22 failed**, 0,17 секунды — новый модуль отсутствовал. Frozen acceptance не менялась. Targeted **53 passed**, 0,31 секунды: 22 metadata acceptance, 9 дополнительных edge/inert cases и 22 прежних restore acceptance. Проверены exact reverse selection/affinity/Unicode roundtrip, revision max без rounding, typed UUIDs, повреждённый package/foreign source, nested input/output isolation и mutated frozen input.

Полный `bash scripts/check.sh`: **1992 passed, 24 subtests passed**, 68 предупреждений, **189,86 секунды**, exit 0. Ruff/format прошли; прежние tests/source/DTO не менялись. Логи .runtime/d03-16b2a-red.log, d03-16b2a-targeted.log, d03-16b2a-full-check.log. Source после gate не менялся.

Baseline рабочих схем/ревизий/счётчиков совпал; ara_test пуста, временных ara_check_* нет. DOCX artifacts не создавались, metadata codec не изменяет Word XML/bytes; render не нужен. Секреты/архив/чужие изменения/БД/API/dependencies/runner/tasks/progress не затронуты. Локальный commit без push, PostgreSQL оставлен для следующего цикла.

Граница: PendingSave.request_sha256 здесь проверяется по форме. Проверка fingerprint с document_id/base/checkpoint revision и receipt требует контекста storage/save слоя; нельзя выдавать успешный decode за факт сохранения. Следующий B2B — SQL checkpoint CAS и legacy arbitration, с отдельным ограниченным контрактом. Продолжать Sol 6.1 High автоматически.
