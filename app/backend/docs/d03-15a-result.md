# D03-15A — единая история операций DOCX

31 октября 2026. Контракт [D03-15A](d03-15a-contract.md), Sol 6.1 High. Реализованы DocxSession.apply_boundary/apply_structure/apply_formats с общим private accept-changed механизмом прежнего RangeEdit. Все виды операций используют одну историю exact DOCX snapshots. Публичные DTO, прежний apply/undo/redo/mark_saved и старые tests сохранены.

Фактическая команда/batch создаёт одну позицию undo и увеличивает session revision. No-op и ошибка сохраняют redo, новая ветвь его очищает. Undo/redo восстанавливают точный пакет вместе с numbering/styles, saved digest работает через все виды правок, сохранение не очищает историю. Лимиты состояний/байтов и ошибки подготовки ответа атомарны. Импорт/операции не выполняют внешнего I/O. Это in-memory backend; controller/курсор/клавиши и crash recovery ещё не подключены.

Freeze **0e436fa**, red **12 failed**, 0,15 секунды. До freeze pure fixtures и точные byte-budget предпосылки проверены отдельно. Frozen acceptance не менялась. Целевые новые/старые session tests плюс два cross-family join/numbering/eviction cases: **77 passed**, 0,72 секунды.

Полный bash scripts/check.sh: **1779 passed, 24 subtests passed**, 73 предупреждения, **169,64 секунды**, exit 0. Ruff/format проходят, old tests не ослаблены/не пропущены. Source после gate не менялся. Логи .runtime/d03-15a-red.log, d03-15a-targeted.log, d03-15a-full-check.log.

QA synthetic rich: split heading → format Heading2 → undo обоих шагов до точного исходника → redo обоих шагов → mark_saved. Каждый пакет совпал с pure oracle; final revision=6, undo_depth=2, dirty=False. Экспорт 48211 bytes, SHA256 `1239ac34f1e975cc56e97698acfab2f747d75e1b97f759b3794f00db66114529`. Bundled renderer 26.1026.10807: одна страница просмотрена целиком; heading styles, выделения, native lists, merged table, рисунок/ссылка/колонтитулы сохранены без clipping/overlap. Microsoft Word отдельно не запускался. Контроль .runtime/d03-15a-qa/export-check.json.

Baseline схемы/ревизии/счётчиков совпал, ara_test пуста, временных ara_check_* нет. PostgreSQL оставлен для следующего цикла. Секреты, архив, чужие dirty-файлы, runner/tasks/progress/dependencies/HTTP/БД/миграции/UI не менялись. Локальный commit разрешён, push не выполнялся.

Далее автоматически D03-15B, с отдельными bounded subcycles для selection history и для compound Enter/typing policy. Составная пользовательская команда пока не считается реализованной вызовом двух методов: потребуется закрытый candidate и одна публикация. Режим остаётся Sol 6.1 High.
