# D03-16E1 — strict wire codec

31 октября 2026, Sol 6.1 High, F05/F06/F11/F12. Реализован d03-16e1-contract.md: pure decode_open/command/control→strict native kwargs/DTO и explicit bounded encode_reply/encode_projection→UTF-8 bytes. Canonical UUID/64-bit decimal strings, offsets/path integers, no bool/coercion/unknown fields. Native validators/defaults и bounded text/batch/paths сохраняются до clone/hash.

Метаданные всех reply kinds содержат selection/dirty/history/IDs/counters/last/active, но не документ/текст/projection tree. Full structural view — отдельный read-only reply с metadata того же EditorView. Явные whitelists native projection fields исключают DocxSource/_original/StoredDocx/binary data; opaque/notices сохраняются. Technical size/node/text/depth limits возвращают413 без truncation. Generic unknown output types безопасно отклоняются. Valid output path не импортирует storage error boundary без необходимости.

Freeze **3b18468**, red **20 failed**, **0,41 секунды** — wire module отсутствовал. Frozen acceptance неизменна. Targeted **32 passed**, 2 предупреждения, **0,46 секунды**: 20 frozen cases +12 wire edges. Проверены command families, MAX/canonical counters/UUID, nested defaults/direction/affinity, unknown/bool/malformed/oversize input, active/latest counters, all reply kinds, rich table/opaque/notices, metadata size, projection node/text/depth/cycles, no source package leak, detached inputs, inert import/valid/error call без external I/O. В дополнительном тесте импорт внутренних projection records исправлен на их реальное private module до фиксации own tests; frozen tests не менялись.

Полный `bash scripts/check.sh`: **2229 passed + 24 subtests passed**, 70 предупреждений, **225,85 секунды**, exit 0. Ruff/format прошли; source после gate не менялся. Логи .runtime/d03-16e1-red.log, d03-16e1-targeted.log, d03-16e1-full-check.log.

Pure rich QA без БД/изменения package: encode metadata/full structural view/capture decode roundtrip на прежнем visual reference 48211 bytes, SHA256 `1239ac34f1e975cc56e97698acfab2f747d75e1b97f759b3794f00db66114529`. View/source identity согласована, table/notices доступны, selection exact, package bytes отсутствуют в JSON. .runtime/d03-16e1-qa.json. Нового DOCX/render/Word запуска нет — codec не меняет документ.

Ограничения: routes/application lifetime, stream/header/duplicate-key checks и binary responses ещё E2/E3. Нет frontend/таймера/ML/лицензирования или автоматической миграции V8. Runtime/source/storage/native DTO/старые tests/schema/API/dependencies/runner/tasks/progress не менялись. После gate/result/local commit продолжать E2 на Sol 6.1 High.

Baseline рабочих схем/ревизий/счётчиков совпал целиком, ara_test пуста, временных ara_check_* нет. Архив/секреты/чужие изменения не затронуты. Локальный commit без push; PostgreSQL оставлен для следующего цикла. Pure QA metadata1412 bytes, projection36765 bytes, одна таблица/восемь notices; документ не менялся.
