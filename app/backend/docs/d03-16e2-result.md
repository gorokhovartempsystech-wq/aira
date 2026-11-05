# D03-16E2 — HTTP lifetime и JSON editor routes

31 октября 2026, Sol 6.1 High, F05/F06/F11/F12. Реализован d03-16e2-contract.md: девять scoped JSON routes, один EditorRegistry на explicit app lifetime, metadata-first replies и отдельный structural view. Health-only приложение и import остаются inert; caller engine не закрывается, рабочая БД автоматически не мигрируется.

Bounded streaming transport проверяет media/encoding/дубликаты headers/CL/TE, UTF-8/JSON duplicate keys/unknown fields/query и canonical UUID до dispatch. Nonblocking per-app gate ограничивает одновременно удержанные body/reply, охватывает worker и отправку ответа, освобождается при ошибках/потере ответа. Shield сохраняет исход уже отправленной команды при отмене HTTP task. Все новые paths, включая ошибки/404/405, no-store. Sanitized envelope не содержит текст документа; local-dev не является продуктовой авторизацией. OpenAPI содержит строгие request variants/string counters и разрешимые references.

Freeze **1ce679f**, red **12 failed**, 3 предупреждения, **2,75 секунды**. Frozen acceptance неизменна. Старый exact route test расширен только девятью согласованными paths; остальные AST assertions неизменны. app.py меняется только deferred import/install в explicit runtime branch, проверено AST comparison.

Targeted **38 passed**, 4 предупреждения, **5,30 секунды**: 12 frozen, 16 transport edges, прежние boundary/health проверки. Дополнительные сценарии: streamed/disconnected requests без dispatch, ambiguous headers и mismatched length, gate busy/release, generic failure sanitization, lost-send applied once + exact retry, cancellation удерживает gate до окончания worker, inert construction/import, duplicate install. В собственном unfrozen inert harness разрешено только framework-чтение PYDANTIC_DISABLE_PLUGINS с постоянным None; реальные environment values не читаются. Старые health tests неизменны.

Полный `bash scripts/check.sh`: **2257 passed + 24 subtests passed**, 70 предупреждений, **244,58 секунды**, exit 0. Ruff/format прошли. Логи .runtime/d03-16e2-red.log, d03-16e2-targeted.log, d03-16e2-full-check.log. Source после gate не менялся.

Rich HTTP QA в собственной disposable БД: import→inspect/open→view→capture/Enter/format→save/replay/reconcile→close→new-app recovery. Current точно равен candidate, storage revision2/receipt1/checkpoint4; original неизменен. Результат **48211 bytes**, SHA256 `1239ac34f1e975cc56e97698acfab2f747d75e1b97f759b3794f00db66114529`, точно совпадает с ранее визуально проверенным reference. Нового render/Word запуска нет. .runtime/d03-16e2-qa.json; временная БД удалена.

Baseline схем/ревизий/счётчиков совпал целиком, ara_test пуста, временных ara_check_* нет. Первой sandbox-попытке snapshot недоступен Unix socket; обычный escalated read-only запуск прошёл, данные не изменялись. Архив/секреты/чужие изменения не затронуты. Локальный commit без push, PostgreSQL оставлен для следующего цикла.

Ограничения: binary saved/working/recovery downloads, explicit discard и SQL deadlines ещё E3. Structural view не является Word rendering. Нет frontend/таймера/реального ML/лицензирования/desktop-поставки. Продолжать E3 по отдельным bounded contracts на Sol 6.1 High.
