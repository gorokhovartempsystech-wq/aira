# D03-15B3 — ввод текста и typing format после Enter

31 октября 2026. Выполнен [контракт](d03-15b3-contract.md) на Sol 6.1 High. EditorSession.insert_text вставляет XML-safe single-paragraph текст по collapsed code-point caret, включая новый пустой paragraph без run/span. Прямые свойства нового run берутся у выбранной affinity стороны; существующие runs/controls/стили не flatten-ятся. Свойства pPr/rPr могут иметь локальные xmlns; они сохраняются в перенесённой run-оболочке. Caret после ввода получает affinity left, продолжая только что введённый формат.

Enter с неизменным style/list identity теперь сохраняет direct typing format в пустом styled run нового p до единственной публикации шага. При next-style/list exit старый формат не переносится. Seed входит в DOCX snapshot и core budgets, без отдельной скрытой mutable font-state и новых полей публичных DTO. Undo/redo восстанавливают его вместе с файлом. Input/reply/лимиты/защита атомарны; пустой ввод — no-op с сохранением redo.

Freeze **454cc7b**; red **13 failed**, 0,12 секунды. Frozen acceptance не менялась. Targeted **46 passed**, 0,46 секунды: 13 frozen typing, 18 прежних intents, 7 прежних history и 8 дополнительных namespace/control/protection/inclusive-limit/inert cases. Новые tests помещены в уже собираемую tests/docx_session.

Общий `bash scripts/check.sh`: **1841 passed, 24 subtests passed**, 67 предупреждений, **174,11 секунды**, exit 0. Ruff/format проходят; старые tests и проверки не ослаблены/не пропущены. Source после полного gate не менялся. Логи .runtime/d03-15b3-red.log, d03-15b3-targeted.log, d03-15b3-full-check.log.

Визуальный QA: Heading→Enter→body text и italic/color body→Enter→continued text. Четыре intents создали четыре history steps; полный undo вернул exact исходник/selection, redo — exact итог. Экспорт 2990 bytes, SHA256 `668ebbf4f1c27a8b5b2eede16070543b77f947b12d117ef36d0b6ae9eef8d0f2`. Bundled renderer 26.1026.10807: единственная страница просмотрена целиком, body после heading обычный, italic/color продолжаются в новом p; clipping/overlap нет. Microsoft Word отдельно не запускался. Контроль .runtime/d03-15b3-qa/export-check.json.

Baseline схемы/ревизии/счётчиков совпал; ara_test пуста, временных ara_check_* нет. PostgreSQL оставлен для продолжения. Секреты/архив/чужие dirty-файлы/old core exporters/UI/HTTP/БД/dependencies/runner/tasks/progress не менялись; push/сообщений нет.

Ограничения: только collapsed single-paragraph insert, без TAB/LF/CR; максимум 100000 code points за вызов, прежние paragraph-node/package budgets сохраняются. Один вызов создаёт один intent/run; объединение DOM typing events — будущая интеграция. Нет multiline paste/selected-range replacement/soft break/DOM/IME bindings или durable recovery. Далее отдельный D03-15C — plain-text paste с native tabs/paragraph boundaries и безопасной заменой выделения в одном p; затем мягкий line break и durable working state. Продолжение автоматически на текущем режиме.
