# D05-05D2 — retained backup и bounded upgrade

4 ноября 2026. [Контракт](d05-05d2-contract.md), freeze **b4cf8e4**.
Реализован owned V12→V13 upgrade на macOS: полный custom archive на exported
repeatable-read snapshot, проверка копии, transactional DDL, durable upgrade
intent и атомарный обмен schema receipts. Existing documents и PG identity
сохраняются. [Подключение и границы](desktop-postgres-upgrade.md).

Первичная приёмка **23failed**,58.47s, когда реализации ещё не было. Первый source
прогон18failed/5passed обнаружил отсутствующий re-export физической SQL-проверки;
source исправлен. Затем **23passed**,33.05s: реальный restore в другой temporary
PG сохранил exact StoredDocx, late committed write исключён exported snapshot,
шесть crash cuts восстановились без пересоздания БД. Orphan backup после сбоя
до upgrade intent сохраняется, повтор делает новый снимок.

Дополнительный review **22passed,1failed**,16.78s: отсутствующий archive возвращал
общую ошибку вместо recovery_required. Исправлена классификация этого исхода;
никакого восстановления/перезаписи данных ошибка не выполняла. Combined D1+D2
**77passed**,75.69s. Первый full: **4847passed,45skipped,24subtests,79warnings**,
746.02s,exit0.

Затем отдельная проверка shutdown обнаружила OverflowError на `10**1000` до
штатного validation_error. Red1failed/23deselected,1.67s; порядок предикатов
исправлен только в D2. Final edge review **24passed**,20.27s. Финальный
`bash scripts/check.sh`: **4848passed,45skipped,24subtests,78warnings**,752.26s,exit0;
Ruff/format green. Цикл завершён на проверенном окончательном source.

Test preparation fix, разрешённый разделом приёмки контракта: одна строка late
write теперь обращается к `docx_documents`, где действительно лежит синтетический
DOCX, вместо старого `documents`. Assertions snapshot/restore/source preservation
не ослаблены. Frozen contract/lifecycle/recovery files unchanged; старые тесты
не редактировались. Единственный прежний source change — разрешённый перенос D1
process claim/release в общий migration gate, чтобы D1/D2 не использовали глобальный
Alembic context одновременно даже на разных Home.

Native проверки также покрывают Stop до/после COMMIT, поздний deadline в cleanup,
unknown thread/SQL close, private backup metadata, чужую identity/SQL version,
исчезнувшую/повреждённую копию, ошибку pg_dump/TOC/диска, лимит размера/числа bundles,
symlink, active fence и advisory contention. Нет force kill/автоматического restore,
удаления старых копий, adoption основной development V8 или новой SQL migration.

Финальный hash manifest — `.runtime/d05-05d2-hashes.json`,681 paths;
666 previous paths unchanged, единственное разрешённое D1 runtime exception выше.
Все681 final hashes совпали после прогона. Readonly main snapshot совпал с D1:
`0008_docx_edit_drafts`, прежние schema/counts, ara_test пустая, temporaryDB0.
Содержимое пользовательских строк не читалось.
Логи `.runtime/d05-05d2-{red,targeted,review,regression,timeout-red,review-final,full}.log`;
первый full сохранён как `d05-05d2-full-before-timeout-review.log`.

Windows implementation/native release gate, desktop composition/build, реальная
модель и frontend остаются отдельными этапами. V12 — синтетический совместимый
predecessor, существование выпущенной V12 не утверждается. Следующий независимый
цикл D05-06A связывает рабочие SQL connections редактора/supervisor с owned Home/PG;
Windows не исключается, Mac wiring выполняется первым ради native сквозной проверки
на доступном хосте. Текущая Astra подходит, продолжаем. Ориентир20–31 самостоятельный цикл по
оставшимся DOCX/desktop/adapter/финальным блокам; внешние release gates отдельно.
