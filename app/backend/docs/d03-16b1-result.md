# D03-16B1 — схема полного checkpoint

31 октября 2026, Sol 6.1 High. Выполнен d03-16b1-contract.md: additive миграция 0009_docx_editor_checkpoints и ORM DocxEditorCheckpoint. Отдельный full-package slot с monotonic checkpoint_revision, empty/working/pending, base/digests, BYTEA и JSONB metadata. Поля NULL согласованы с phase; missing pending key не проходит SQL UNKNOWN. Технические границы ZIP 32 MiB и metadata text 64 KiB; app validation/canonical bound будут в B2.

Downgrade получает ACCESS EXCLUSIVE lock до проверки rows и отказывается удалять working/pending. Empty tombstones допускают clean downgrade. Данные прежних таблиц не преобразуются, нет implicit cascade. Python checkpoint_metadata отображает SQL metadata, не конфликтуя с Base.metadata.

Freeze **fd57d8f**, red **19 failed**, 2,94 секунды — отсутствовали V9/table/model. Frozen новая приёмка не менялась. Согласно контракту ровно два вызова fixture старого V8 migration test привязаны к V8; все его assertions/данные/проверки repeat/downgrade сохранены. Новый test отдельно проверяет V8→head V9, всю старую schema/rows и повтор/downgrade.

Targeted: **43 passed**, 8,10 секунды (новая frozen schema, прежний recovery и CLI ORM/migration parity). Отдельный schema/edges прогон: **32 passed**, 5,73 секунды — 19 frozen + 13 дополнительных. Первые дополнительные тесты не видели fixtures из соседней папки acceptance; добавлены явные fixture imports, затем прогон успешен. Это исправление test setup, frozen assertions не менялись.

Проверены inclusive 33554432-byte package и 65536-byte metadata/отказ на +1, rollback failed UPDATE, PK/FK без cascade, cross-phase NULL, настоящая гонка downgrade с незавершённым INSERT. Downgrade ждёт commit writer и затем отказывается; новая рабочая копия и revision V9 сохраняются. До реализации runtime SQL shape намеренно не доказывает валидность DOCX/package hash или вложенных selection/origin — их обязан проверять B2.

Полный `bash scripts/check.sh`: **1961 passed, 24 subtests passed**, 69 предупреждений, **184,44 секунды**, exit 0. Ruff/format прошли; существующие проверки не пропускались. Логи .runtime/d03-16b1-red.log, d03-16b1-targeted.log, d03-16b1-schema-targeted.log, d03-16b1-full-check.log. Source после gate не менялся.

Миграции выполнялись только на disposable PostgreSQL DB. Рабочие ara_dev/ara_test автоматически не мигрировались: схемы/ревизии/счётчики совпали с baseline, временных ara_check_* нет. PostgreSQL оставлен для следующего цикла. DOCX artifacts/visual render не требовались для schema-only задачи. Секреты/архив/чужие dirty-файлы/API/runner/tasks/progress/dependencies не менялись; локальный commit без push.

Следующий B2 уточняется на B2A (pure формат/проверка checkpoint metadata и package) и B2B (SQL checkpoint CAS/legacy arbitration) для отдельных приёмок. Это разбиение прежнего объёма, без добавления функций. Оба на Sol 6.1 High, работа продолжается автоматически.
