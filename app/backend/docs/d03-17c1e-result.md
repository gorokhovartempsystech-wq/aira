# D03-17C1E — результат проектирования Windows

2 ноября 2026, Astra 6 High, запрос Никиты после macOS D3 `5796c16`. **Проектирование завершено**, подготовлены [Windows lifecycle](d03-17c1e-design.md) и [контракт первого цикла E1](d03-17c1e1-contract.md); статусные ссылки C1/очереди обновлены. Поведение приложения и source/tests не менялись. Это не реализация и не native Windows acceptance.

Основные решения:

- Atomic Job assignment при CreateProcess через JOB_LIST, без fallback create→assign и без startup orphan handoff. Microsoft API/documented explanation проверены; ссылки рядом с решениями в design.
- S владеет outer Job для G/M, G — inner Job для M; kill-on-last-close, no inherited Job handles, no breakaway, threads-only pack. Потеря status даже при пустом outer Job не становится successful analysis/подтверждённым M wait.
- Private file HANDLE reservation остаётся у child после смерти parent; новый запуск требует independent slot probe и отдельного SQL reconciliation. Owner handle только у S.
- Clock считает сон; OS wait не заменяет deadline. Stop идёт через отдельные events, не ждёт большого request/reply. Overlapped cancellation не освобождает buffer до actual completion.
- Четыре реализации: **E1 clocks/ABI/owner/slot**, **E2 pipes/events/pending IO**, **E3 jobs/guardian/bootstrap**, **E4 parent driver/candidate/fault matrix**. Точные API/ACL/path/errors/allowed paths/acceptance E1 готовы; следующие exact contracts/freeze перед соответствующим кодом на Sol.

## Проверка и сохранность

**`bash scripts/check.sh`:3247 tests +24 subtests passed,78 warnings,425,05s,exit0.** Ruff/format398files прошли; `.runtime/d03-17c1e-design-full-check.log`. Это регрессия существующего Mac backend, не проверка ещё не написанных Windows primitives. Новые acceptance/source не создавались; искусственный red в документационном цикле не имитировался. Freeze/red E1 — первый шаг реализации.

Read-only `d03-17c1e-design-start-runtime.json` совпал с baseline D3, `-final-runtime.json` совпал со start: main V8/schema/counts unchanged, ara_test пуста, временных ara_check0. Проверены только schema/revision/counts, без содержимого строк. PostgreSQL оставлен запущенным. Один запрос автоматического согласования итогового snapshot истёк по времени; разрешённый повтор успешно выполнил ту же read-only сверку, обходов нет.

UTF-8/relative links/git diff checks выполнены; собственные изменения только пять design/status docs. Старые source/tests/contracts/DDL/runner/tasks/progress/dependencies и чужие dirty README/specs/материалы сохранены. Архив/секреты/Word/реальный engine не использовались; внешнее чтение только публичной технической документации Microsoft. Локальная фиксация собственных документов, без push/публикации/миграции.

## Передача

**Сейчас возвращаться на Sol 6.1 High и реализовать D03-17C1E1.** Затем продолжать E2–E4 отдельными циклами по прежнему разрешению Никиты, если не обнаружится новое архитектурное противоречие. Новых продуктовых вопросов для первого цикла нет.

На этом Mac Windows APIs не запускались. Windows11 x64/NTFS — первая technical acceptance configuration, не утверждённая окончательная продуктовая матрица. Native inheritance/Job/cancellation/crash/suspend tests остаются обязательными; mocks не закрывают их. При недоступной Windows можно завершать доступный код/проверки и идти к независимым задачам, явно сохраняя native gate pending и не объявляя готовность Windows/релиза.

Самостоятельный остаток **30–45 циклов**: после D3 было27–42, раскрытие одного C1E в четыре реализации добавило3. Новых продуктовых функций нет, этот законченный design повторно не считается. C1F SQL scheduler/recovery, реальный C2 pack/weights, полноценный DOCX/Word, лицензирование, поставка и итоговая интеграция остаются впереди; работа Ани/Артёма и недоступные native environments отдельно. Оценка не гарантированный потолок.
