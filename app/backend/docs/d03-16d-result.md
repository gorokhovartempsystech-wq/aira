# D03-16D — архитектурный проход завершён

31 октября 2026, Astra 6 High, основание 6a091ef. По прямому запросу Никиты спроектирована runtime-часть D перед реализацией. Изменено техническое описание, production code/БД/HTTP поведение не изменены.

Результат: [d03-16d-design.md](d03-16d-design.md), точный первый [d03-16d1-contract.md](d03-16d1-contract.md), актуальная development-queue.md. Прежний d03-16-design.md ссылается на уточнение; review-brief отмечен историческим входом. Product scope не расширен, frontend Ани не переписывается.

Зафиксированы:

- Registry lifetime/scope, новая epoch, bounded open sequence вместо неограниченного closed-ID cache. Late open после release не воскрешает actor.
- Passive согласованное recovery read, pending open без записи, новый local SaveTarget вместо historical origin.
- Exact command ordering/latest retry/no-op sequence, native fork→validated reply→успешный read transaction→RAM publication.
- Project/document lock order, отсутствие outer SQL lock вокруг C1/C2/C3, отдельные actor/open locks и краткий index lock.
- Immutable attempt/полный ожидаемый SaveHandle до первого prepare, recovery при потере любого ответа, positive receipt confirmation отдельно от актуальности current.
- Сохранение undo/redo после save, default checkpoint-close и отдельное explicit release только RAM; отказ не запускает silent discard. Release не требует counter+1 после исчерпания sequence.
- Retained memory union по bytes object identity, private read-only introspection, admission без eviction. Compressed budget не выдан за hard RSS limit.
- Exact SavedTarget для анализа/экспорта, manual serializers и отдельный будущий transport gate.

Разобраны 12 последовательностей событий (§10 дизайна), включая another-controller finalize после prepare ACK-loss, ошибку DTO после commit, чужой head при одинаковых bytes, close/open replay и counter exhaustion. Это ручная архитектурная проверка по актуальному source, не заявление о выполненных новых runtime tests. Поведение pure copy/restore, C1 fingerprints, C2 receipt replay, C3 finalize/discard и safe transaction boundary сверено с кодом. Новые executable acceptance tests фиксируются до реализации каждого следующего цикла; старые tests/criteria не менялись.

Обязательная общая проверка `bash scripts/check.sh` прошла: **2086 passed + 24 subtests passed**, 68 предупреждений, **200,68 секунды**, exit 0; Ruff/format также прошли. Лог .runtime/d03-16d-full-check.log. Это regression baseline готовых A–C3B, не доказательство работы будущего D. После gate менялись только документы; повтор code tests не требуется.

Схемы/ревизии/счётчики рабочих баз совпали до/после, временные тестовые базы удалены. ara_dev осталась V8, ara_test пуста. PostgreSQL этого проекта после проверки остановлен с сохранением данных. Секреты/архив/чужие изменения не читались и не менялись; runner/tasks/progress/dependencies/production source untouched. Локальный commit без push.

**Возвращаться на Sol 6.1 High можно сейчас.** Реализовывать последовательно D1→D2→D3A→D3B→E; перед каждым собственный contract/acceptance freeze/red, затем код/targeted/full gate/result/local commit. D1 contract уже готов, исходники ещё не написаны. Пользователь разрешил автоматическое продолжение циклов, снова спрашивать обычное разрешение не нужно.

Ограничения: runtime/HTTP/UI ещё предстоит реализовать; SQL deadlines/cancellation проверяются в E, Windows/macOS/Word — отдельный gate. Рабочая V8 требует обычного перехода на V9 перед применением новых storage API; сейчас она автоматически не мигрировалась. ML/веса/лицензирование не входят в D и не блокируют эти циклы.
