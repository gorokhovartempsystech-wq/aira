# D05-05B — native macOS command ownership

4 ноября 2026. [Контракт](d05-05b-contract.md), freeze **989c150**. Реализован
OwnedCommand: отдельный guardian, inherited slot, direct-child SIGTERM/wait,
bounded stdout/diagnostics и strong quarantine неизвестного cleanup.
[Интерфейс/ограничения](desktop-postgres-process.md).

Native preflight на временном PG18.6 подтвердил inherited slot, busy admission,
smart shutdown с открытым connection, COMMIT и повторное чтение сохранённой строки.
Red acceptance **32failed**,0.40s — namespace отсутствовал. После реализации:
portable/native primitive **30passed**,2.02s; реальные PG scenarios **2passed**,1.51s.

Additive review8 cases: startup failure после фактического окончания worker,
Thread constructor failure, descendant slot после wait прямого child, concurrent
Stop, nonfinite/duplicate/oversized status. Первый review **5failed,3passed**,1.06s:
найдены startup-return race и недопустимое преобразование nonfinite JSON в null.
Исправлены source: outcome latch до освобождения registry, fixed constructor failure,
strict parse_constant rejection. Frozen acceptance не менялась. Review **38passed**,
2.83s; окончательный combined targeted/native **40passed**,4.25s.

`bash scripts/check.sh`: **4720passed,45skipped,24subtests,80warnings**,
673.37s,exit0. Ruff/format green. Все645 final hashes и633 previous hashes совпали.
Main `0008_docx_edit_drafts`, schema/counts прежние, ara_test пустая, temporaryDB0.
Логи `.runtime/d05-05b-{preflight,red,targeted,native,review-red,review,regression,full}.log`,
hash manifest `d05-05b-hashes.json`, snapshot `d05-05b-runtime.json`.

Старые source/tests/dependencies/runner и Main V8 не менялись.
Не объявляются готовыми Windows lifetime, durable cluster bootstrap/schema/backup,
desktop composition или автоматическое управление orphan PG после потери guardian.
Следующий самостоятельный этап **D05-05C** готовит persistent cluster с сохранением
имеющихся данных и отдельным подтверждением SQL readiness. Ориентир20–31 оставшихся
самостоятельных циклов; текущая Astra, продолжаем без смены режима.
