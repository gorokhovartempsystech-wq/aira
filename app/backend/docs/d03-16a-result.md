# D03-16A — восстановление рабочей сессии

31 октября 2026, Sol 6.1 High. Выполнен контракт d03-16a-contract.md: DocxSession.restore и EditorSession.restore принимают exact working bytes и проверенный caller saved digest; editor также восстанавливает source-bound selection/affinity. Начальные revision/position=0, undo/redo пусты; dirty вычисляется относительно сохранённого digest. Нет fake edit/base undo, обычные constructors остались clean.

Digest строго lowercase hex64/настоящий str; package/projection/history limits прежние и копируются. Повторно проверяются вложенные frozen DTO; private state не ссылается на caller selection/limits/projection. После подготовки всего ответа factory возвращает объект; ошибки не затрагивают другие живые сессии. Источник сохранённого digest должен проверить будущий storage слой; pure factory сам не подтверждает факт сохранения на диск.

Freeze acceptance **70c389d**, red **22 failed**, 0,17 секунды — отсутствовали новые методы. Frozen acceptance не менялась. Targeted **32 passed**, 0,55 секунды: dirty/clean, обратное межабзацное выделение/affinity/non-BMP, typing/Enter/paste/format/split undo/redo, strict invalid/mutated input, budgets, reply failure, opaque selection, rich exact identity и first-import/restore inertness.

Полный `bash scripts/check.sh`: **1929 passed, 24 subtests passed**, 70 предупреждений, **172,56 секунды**, exit 0; Ruff/format прошли. Старые тесты не менялись/не пропускались. Source после gate не менялся. Логи .runtime/d03-16a-red.log, d03-16a-targeted.log, d03-16a-full-check.log.

QA без новой генерации DOCX: restored rich-source exact совпал с ранее визуально проверенным .runtime/d02-01-visual/rich-source.docx; SHA256 `73009626640400679d2b1a2031c565a964308073aa287067cf39088836176fcd`, 48126 bytes, dirty=true. Единственная reference page повторно просмотрена целиком: таблица/рисунок/списки/колонтитулы сохранены. Это hash proof reuse, не новый render или запуск Microsoft Word. Контроль .runtime/d03-16a-qa.json.

Схемы/ревизии/счётчики рабочих баз совпали с baseline, ara_test пуста, временные ara_check_* удалены. Секреты/архив/чужие изменения/API/БД/dependencies/runner/tasks/progress не затронуты. Локальный commit без push; PostgreSQL оставлен для следующего цикла.

Ограничение: pure восстановление из уже полученных bytes/metadata; durable checkpoint, receipt reconciliation и frontend ещё не подключены. Следующий D03-16B1 — отдельная миграция/ORM checkpoint-slot, собственные frozen contract/acceptance. Продолжать Sol 6.1 High, обычное разрешение «продолжи» не требуется.
