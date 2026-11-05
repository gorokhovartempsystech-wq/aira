# D03-15C — plain-text paste и однопараграфная замена

31 октября 2026. Выполнен [контракт](d03-15c-contract.md), Sol 6.1 High. Новый paste_text и PasteLimits, единый bounded lexical patch вместо последовательного выполнения множества exports. Вставка/однопараграфная замена (включая reverse selection) создаёт одну позицию exact истории; ошибки/reply/лимиты полностью сохраняют source/caret/history.

CRLF/CR нормализуются в LF, LF создаёт p, TAB — native Word tab. Пустые начальные/конечные/повторные строки сохраняются. Все p наследуют исходные pPr/style/list ID, без Enter next-style/выхода из списка. Inline формат исходных prefix/suffix сохраняется, clipboard text получает один выбранный run template; trailing empty line имеет typing seed. Новые paragraph IDs не дублируются. Same-text single-line replacement меняет только selection, сохраняя bytes/redo/ID; LF не путается с native soft break. Пустая замена выделения удаляет ровно выбранный текст; multi-p selection отклоняется.

Freeze **8c655c5**, red **16 failed**, 0,13 секунды. Frozen acceptance не менялась. Targeted: **58 passed**, 0,60 секунды — 16 frozen paste, 13 typing, 18 intents и 11 дополнительных encoding/namespace/equality trap/limits/amplification/rich preservation/inert cases. TAB payload строится ленивыми chunks с бюджетом, не создавая полный потенциально огромный XML перед проверкой.

Полный `bash scripts/check.sh`: **1868 passed, 24 subtests passed**, 68 предупреждений, **171,34 секунды**, exit 0. Ruff/format проходят; старые проверки не ослаблены/не пропущены. Source после gate не менялся. Логи .runtime/d03-15c-red.log, d03-15c-targeted.log, d03-15c-full-check.log.

QA: AIRA numbered-list paste с CRLF, native TAB и пустой строкой clipboard. Один paste — один undo step, точный возврат исходного DOCX/selection, redo — точный итог. Экспорт 2974 bytes, SHA256 `6af2106453ee1afe304bec24c821b6495f6a83e1d8db5fcf2c79e2d21023b5dc`. Bundled renderer 26.1026.10807, одна страница просмотрена целиком: список 1–4, native tab alignment, намеренно пустой пункт 3 из clipboard, без clipping/overlap. Пустой пункт не считается случайной потерей текста. Microsoft Word отдельно не запускался. Контроль .runtime/d03-15c-qa/export-check.json.

Baseline схемы/ревизии/счётчиков совпал; ara_test пуста, временных ara_check_* нет. PostgreSQL оставлен для следующего цикла. Секреты/архив/чужие dirty-файлы/старые core exporters/DTO/UI/HTTP/БД/dependencies/runner/tasks/progress не менялись; публикаций и сообщений нет.

Ограничения: plain-text clipboard и один исходный p, без HTML/rich clipboard или выделения через несколько p. Нет DOM bindings/IME grouping/durable recovery. Следующий D03-15D — native soft-break intent (Shift+Enter semantics), отдельно от настоящих p boundaries; затем нужен точный проект durability/старого checkpoint-протокола D03-16. Работа продолжается на текущем режиме.
