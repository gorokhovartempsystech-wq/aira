# D03-16C3A — подтверждённый finalize и status

31 октября 2026, Sol 6.1 High. Выполнен d03-16c3a-contract.md: get_save_status классифицирует receipt/pending/current без записи, finalize_save снимает pending только с matching receipt/current и full control proof. Working bytes/selection/origin прежние, base=receipt, checkpoint revision+1; original/current/receipt ledger не меняются. Restore из working результата clean, новая история пуста, live mark_saved остаётся controller D.

Повтор с тем же request ID или восстановление той же операции другим request ID подтверждаются canonical stored control fingerprint и полным working result, без нового increment/timestamp. Только bytes не являются доказательством. Другой counter/action/request/payload безопасно отказывает, data contradiction при matching proof ->stored error. Completed replay может показать newer current отдельно, current_matches_receipt=false; чужой checkpoint не очищается.

Закрыта обнаруженная protocol boundary: fresh prepare теперь резервирует шаг finalize (expected checkpoint revision≤MAX−2), fresh commit legacy pending с prepared revision=MAX запрещён. Последний допустимый prepare→commit→finalize достигает MAX корректно и повторяется без increment; старое exhausted pending остаётся readable/status exhausted. Старые matching receipt replay сохраняются. Изменены только соответствующие fresh guards C1/C2; их frozen tests не менялись. Три прежних save DTO class AST также сверены с HEAD — без изменений.

Freeze **5ac38d6**, red **10 failed**, 2,29 секунды: новый module отсутствовал, отдельная counter regression не получала требуемый отказ. Frozen acceptance после freeze не менялась. Targeted **35 passed**, 7,79 секунды, 2 предупреждения — 10 finalize acceptance, 8 commit acceptance, 7 prepare acceptance и 10 дополнительных finalize edges. Проверены before/after-commit cleanup ACK-loss, два параллельных recovery, control action/data contradiction, corrupt receipt, read-only superseded status, input/output isolation/scope, separate-process clean restore/finalize, import inertness.

Полный `bash scripts/check.sh`: **2066 passed, 24 subtests passed**, 69 предупреждений, **191,54 секунды**, exit 0. Ruff/format прошли. Source после gate не менялся. Логи .runtime/d03-16c3a-red.log, d03-16c3a-targeted.log, d03-16c3a-full-check.log.

Отдельная disposable QA DB: полный prepare→commit→finalize→restore на synthetic rich DOCX. Current exact совпал с ранее просмотренным reference 48211 bytes, SHA256 `1239ac34f1e975cc56e97698acfab2f747d75e1b97f759b3794f00db66114529`; original exact, current revision2/receipt1, checkpoint working revision3, pending=None, restored clean/undo0. Другой finalize request распознал тот же completed result без изменений. Hash-proof reuse последнего осмотра единственной reference page в C2, нового render/Word запуска нет. .runtime/d03-16c3a-qa.json; собственная QA DB удалена.

Baseline схемы/ревизии/счётчиков рабочих баз совпал, ara_test пуста, временных ara_check_* нет. Рабочие базы автоматически не мигрировались, runtime требует V9. Секреты/архив/чужие изменения/старые tests/schema/API/dependencies/runner/tasks/progress не затронуты; local commit без push. PostgreSQL оставлен для следующего цикла.

Ограничение: явный discard_pending и удобный reconcile pipeline ещё впереди — отдельный C3B. Controller/HTTP/handoff после него. Продолжать Sol 6.1 High автоматически.
