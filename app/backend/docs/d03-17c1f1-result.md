# D03-17C1F1 — dispatcher и безопасная доставка публикации

3 ноября 2026, Sol6.1 High. Реализован [контракт F1](d03-17c1f1-contract.md) в пяти новых модулях supervisor. Import/construction инертны; один явно вызываемый step владеет C1A, хранит Thread object для affinity. Нет фонового loop, SQL, OS launch или изменения runtime startup.

Stop/child/lease/publication имеют отдельные bounded cells. Новый heartbeat считается принятым только после свежей проверки старой L, original s+duration-guard и fixed D. LeaseDecision не подменяет ACK G. PublicationPort совместим с существующим C1B: reserve offered/taken разделены, недоставленный token откатывается один раз; taken/unknown token не теряется по timeout. Settlement non-cancellable: потерянный ACK committed сохраняется до повтора, fallback unknown не затирает success. Ошибка часов отзывает новые grants, но durable committed сохраняется.

Дополнительная проверка выявила две гонки, исправленные в own source: caller sample, снятый до owner tick, не считается регрессией общего clock; при передаче offered token заново проверяется actual L/D. Для обеих добавлены детерминированные regression tests. После истечения L новый reserve не создаёт лишнюю pending cell. Acceptance после freeze не менялась.

## Проверка

Freeze **4f8c79d**: новая независимая acceptance/preflight, перед source red30 failures+6 setup errors (отсутствовал новый пакет). После source acceptance36 passed. Дополнительные own edges: поздний offer/settlement ACK, concurrent publisher, conflicting outcomes, owner thread death/reuse, forged handles, snapshot mutation, clock faults, реальные fork/PID, inert fresh import. Итоговый targeted **58 passed,0,69s**. Нормальные delivery tests используют отдельный управляемый availability clock; deadline/fault проверяются continuous clock и barriers, без надежды на случайное выполнение за50ms.

Первый full:3564passed+24subtests/41skipped,77warnings,399,45s,exit0. Он уже шёл во время двух финальных source fixes и не считается доказательством окончательной версии. Финальный full: **3566passed+24subtests,41skipped,75warnings,408,06s,exit0**, Ruff/format444files прошли. Лог `.runtime/d03-17c1f1-final-full-check.log`. Native skips остаются открытыми gates.

468 прежних source/test/config hashes неизменны. SHA-256 новой acceptance совпадает с freeze; перед финальным gate сохранены475 hashes, включая семь новых code/test files. Все475 hashes совпали после gate; финальный read-only schema/revision/count snapshot совпал со стартом: main V8 `0008_docx_edit_drafts`, ara_test пуста, временных БД нет. PostgreSQL оставлен работающим. Содержимое пользовательских документов не читалось. Runner/tasks/progress/зависимости/старые tests/source не меняются. Чужие dirty README/spec/backlog/research/defense файлы сохранены.

## Следующий цикл и ограничения

На том же **Sol6.1 High → D03-17C1F2 preparation** по [C1F design](d03-17c1f-design.md): exact V11 DDL/ORM, singleton durable ledger, scoped exact claim/heartbeat receipt и restart services, отдельные bounded SQL engines. Перед кодом собственный контракт/acceptance/freeze/red. Main V8 не мигрировать; fixture pg только одноразовая. Нужные V10-only pins оформляются узко в parent preparation, без ослабления assertions. Новое архитектурное противоречие фиксируется до изменения старых контрактов.

F1 не запускает реальную модель, не сохраняет durable fence и не доказывает Windows cleanup/boot recovery. Это внутренняя инфраструктура supervisor; native skips и production provisioning остаются открыты. Actual SQL outcome сообщает trusted C1B; coordinator не угадывает COMMIT по timeout или slot.

После F1 самостоятельный остаток **27–42 цикла** (F1 вычтен один раз); в текущем supervisor блоке остаются F2/F3. Это ориентир нашей части без ожидания фронта/весов и без объявления полного релиза готовым.
