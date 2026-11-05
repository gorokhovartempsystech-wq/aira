# D03-17C1E4 — результат проектирования Windows driver

2 ноября 2026, Astra6 High, после E3 `66f3bc6`. **Проектирование завершено:** [точный контракт E4](d03-17c1e4-contract.md) готов к реализации. Поведение приложения не менялось; source/acceptance E4 ещё отсутствуют. [Исходные вопросы](d03-17c1e4-preflight.md) закрыты на уровне проектирования, не native Windows acceptance.

Выбраны три постоянных владельца на attempt: launch/cleanup, control writer и data pump. Общий startup gate запрещает OS setup при частичном запуске workers. Endpoints передаются только до первой I/O submission, pending обслуживает исходный владелец; E1–E3 менять или сбрасывать их ownership не требуется.

Public renew использует одну bounded command/receipt ячейку без очереди. Полная своевременная запись сначала даёт provisional receipt; local L меняется только при своевременном принятии caller. Timeout, поздний completion, конкурентный Stop и задержанное пробуждение после уже принятого receipt определены отдельно. Stop сигналит R/H независимо от data/control wait, pending не освобождается по одному CancelIoEx. Candidate требует полного request+EOF, всех response/status/armed proofs, actual G exit/count0, живого accepted L/D и отсутствия Stop/fault. Собственная очистка ресурсов, M evidence и SQL ACK остаются разными фактами.

Контракт задаёт bounded mailboxes/threads/buffers,2s tail window без потери pending lifetime, общий timeout close, strong retention при unknown и portable barrier/native fault matrix. Real engine/weights, production wiring, SQL и crash recovery не добавлены. C1F должен отдельно спроектировать durable crash fence и physical+SQL+I/O reconciliation; E4 не разрешает безопасное восстановление по одному свободному slot.

## Проверка и сохранность

`bash scripts/check.sh`: **3442 passed +24 subtests,26 skipped,76 warnings,396,92s,exit0**. Ruff/format429files прошли. Лог `.runtime/d03-17c1e4-design-full-check.log`. Это регрессия существующей реализации на Mac, не проверка ещё не написанного E4.26 native Windows skips остаются pending. Искусственный red для документационного цикла не создавался; новые acceptance/freeze/red обязательны перед source E4.

Все460 source/test/contracts/runner/config файлов совпали с baseline по SHA-256 до/после gate; старт также совпал с финальным E3 baseline. Read-only runtime start snapshot совпал с E3 final, final — со start: main `ara_dev` V8 `0008_docx_edit_drafts`, schema/counts неизменны; `ara_test` пуста, временных check databases не осталось. PostgreSQL оставлен работающим. Содержимое пользовательских документов не читалось.

Собственные изменения — только contract/result и ссылки/статус в C1/C1E/preflight/development queue. UTF-8, относительные ссылки и `git diff --check` проверены. Чужие README/spec/backlog, research/defense материалы, `.artifact-build/` и `output/` сохранены. Архив, секреты, Word, weights, внешние сервисы не использовались. Нет миграций, новых dependencies, runner/task/progress изменений, push или публикации.

## Следующий цикл

**Теперь Sol6.1 High → D03-17C1E4 implementation**: подготовить/проверить новую acceptance, freeze/red → driver source → targeted/full → runtime/hash verification → result/local commit. Не начинать с повторного проектирования handoff и не выдавать fixture reply за настоящий анализ. После completed E4 — Astra6 High для exact C1F lifecycle/recovery contract, затем реализация отдельными согласованными циклами.

Самостоятельный остаток **27–42 цикла**: design уточнил уже учтённый E4, его реализация ещё не вычитается и новый ID не добавлен. Это ориентир, не гарантированный потолок. Native Windows/VM-crash/suspend, Word, настоящий frontend/weights и совместная проверка поставки остаются внешними gates; они не объявлены выполненными этой регрессией.
