# D03-15D — перенос строки внутри абзаца

31 октября 2026. Выполнен [контракт](d03-15d-contract.md), Sol 6.1 High. EditorSession.insert_soft_break заменяет collapsed/однопараграфное forward/reverse selection одним native Word br. Не создаёт новый p, сохраняет исходные pPr/style/list/IDs, prefix/suffix runs и inline formatting. Cursor lo+1 с affinity left; следующий ввод наследует формат break. Единый bounded patch и одна candidate publication/history position; ошибки полностью сохраняют source/caret/saved mark/history.

Freeze **884fa24**; red **14 failed**, 0,13 секунды — во всех случаях отсутствовал новый метод. Отдельный errata **2b34c38** исправляет опечатку нового budget-test (dirty -> is_dirty), без изменения лимита/ожидаемого отказа/сохранности. Старые тесты/DTO не менялись. Остальная frozen acceptance не менялась.

Targeted: **58 passed**, 0,51 секунды — 14 frozen soft-break, 16 paste, 13 typing и 15 дополнительных encoding/Strict/local namespace/selection-direction/empty formatting/history/rich preservation/protection/projection budget/inert cases. Word field-only source остаётся opaque и отклоняется до создания редактируемого selection, не очищается ради переноса.

Полный `bash scripts/check.sh`: **1897 passed, 24 subtests passed**, 72 предупреждения, **171,13 секунды**, exit 0. Ruff/format проходят; существующие проверки не ослаблены и не пропущены. Source после gate не менялся. Логи .runtime/d03-15d-red.log, d03-15d-targeted.log, d03-15d-full-check.log.

QA: AIRA heading + numbered list; native break и следующий ввод сохранили italic/color в первом пункте, второй остался номером 2. Два intents отменены/повторены с точным возвратом bytes/selection, один break — один history step. Экспорт 2992 bytes, SHA256 `d0733f99b12ee394ac528ad9a41a88c24cde48bae0e376450d559dd6b97b4402`, четыре p. Bundled renderer 26.1026.10807, одна страница полностью просмотрена: перенос внутри пункта, отступы/курсив/цвет/нумерация корректны, clipping/overlap нет. Microsoft Word отдельно не запускался. Контроль .runtime/d03-15d-qa/export-check.json.

Baseline схемы/ревизии/счётчиков совпал, ara_test пуста, временных ara_check_* нет. Секреты/архив/чужие dirty-файлы/старые exporters/API/БД/dependencies/runner/tasks/progress не менялись. Локальные commits без push, внешних публикаций/сообщений нет.

Ограничения: backend intent, без DOM/IME/key bindings; multi-p selection отклоняется, несовместимые стили не склеиваются с потерей оформления. Перезапуск ещё не восстанавливает новый controller/history. D03-16 должен отдельно определить durable working state/keyed save/recovery и совместимость прежнего /draft. [Очередь](development-queue.md) содержит конкретные источники/риски и рекомендацию Astra 6 High на один архитектурный цикл, затем Sol 6.1 High для реализации. Текущий цикл завершён перед запросом переключения; обычной команды «продолжи» не требуется.
