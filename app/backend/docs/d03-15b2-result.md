# D03-15B2 — атомарные Enter и boundary join

31 октября 2026. Выполнен [контракт](d03-15b2-contract.md) на Sol 6.1 High. EditorSession получил enter/join_previous/join_next. Составной Enter готовит package и caret до единственного принятия candidate в общую историю; промежуточный split не публикуется. Старые APIs/DTO/pure exporters сохранены.

Enter посреди текста сохраняет оформление, после заголовка применяет валидный next к новому пустому p, в непустом прямом списке продолжает тот же ID, в пустом завершает список без нового p. При смене стиля новый пустой p получает только pStyle, без старых direct overrides/typing runs. Style IDs не угадываются; проверены ссылки/type, basedOn cycles, уникальный default и наследуемая нумерация, включая docDefaults. Inherited list/неоднозначность дают явный unsupported_intent. Join использует прежний compatible primitive и не перескакивает tables/opaque, край документа — no-op.

## Проверки и errata

Freeze **c6b6908**, red **18 failed**, 0,14 секунды. Первый targeted с прежней history acceptance: 22 passed и три ошибочных fixture negatives. Глобальная replace(...,1) меняла Title вместо Heading1. Отдельный **83a3415** ограничил только builders точным диапазоном Heading1 и добавил preconditions; все сценарии/ожидаемые errors/rollback assertions сохранены. Эта errata не выдаётся за дефект реализации или ослабление критериев.

Итоговый targeted: **34 passed**, 0,35 секунды — 18 frozen intent cases, 7 прежних history и 9 дополнительных (UTF8/UTF16/Strict, custom/self next, docDefaults numbering, inert composite calls). Полный `bash scripts/check.sh`: **1820 passed, 24 subtests passed**, 71 предупреждение, **169,37 секунды**, exit 0. Ruff/format проходят; старые проверки не ослаблены/не пропущены. Логи .runtime/d03-15b2-red.log, d03-15b2-targeted.log, d03-15b2-full-check.log. Source после полного gate не менялся.

QA AIRA: Heading1→Enter→Normal и пустой numbered item→Enter→Normal. Два intents создали ровно две позиции undo; полный undo вернул исходные bytes/selection, redo вернул точный итог. DOCX 2979 bytes, SHA256 `5a5ec8d62eadcecf54d08a178d5d6e2575bdff297422d1f235ebaac3705edbe3`. Bundled renderer 26.1026.10807: одна страница просмотрена целиком. Heading/body style, native numbering и завершение списка отображаются корректно, новый пустой paragraph после заголовка намеренно сохранён; clipping/overlap нет. Microsoft Word отдельно не запускался. Контроль .runtime/d03-15b2-qa/export-check.json.

Baseline схемы/ревизии/счётчиков совпал; ara_test пуста, временных ara_check_* нет. PostgreSQL оставлен для продолжения. Старые source вне editor, UI/HTTP/БД/dependencies/runner/tasks/progress/инструкции и чужие dirty-файлы сохранены; секреты/архив не читались, push/сообщения не выполнялись.

## Следующий цикл

Нет DOM/IME bindings, inline typing/вставки в пустой p, pending character formatting или durable recovery. До подключения frontend нужно обеспечить ввод в созданный пустой paragraph и наследование direct run formatting у курсора. Следующий ограниченный D03-15B3 — collapsed single-paragraph text insertion и сохранение typing format после Enter через пустой styled run, в той же snapshot history. Затем отдельные paste/soft break и durable working-state задачи. Работа продолжается автоматически на Sol 6.1 High.
