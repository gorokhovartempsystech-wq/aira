# D05-06B — owned fixture desktop lifecycle завершён

4 ноября 2026. Frozen acceptance d7e4e38; API binding prerequisite f857665.
Основной контракт и дополнение сохранены без переписывания. До реализации:
32 failed1.98s (namespace/drain absent). Первый native integration:6failed26passed4.80s;
обнаружен legacy URL-only analysis binding. Дополнительная независимая acceptance:
1failed4passed11.93s. После bridge оставалась штатная editor OptionEngine wrapper,
поэтому validator принимает только direct wrapper issued engine + exact same pool;
foreign/same URL tests сохранены. `_reads.py` не изменён.

Combined regression:115passed/1failed/1Windows skipped100.73s. Единственный failure —
подготовка нового held-save теста открывала current при существующем checkpoint.
Исправлено на штатное mode=recover; все data/save/restart assertions сохранены.
Следующий короткий прогон дошёл до последнего assertion и обнаружил ещё одну
ошибку тестового ожидания: metadata API возвращает storage_revision числом, не
editor-wire строкой. Ожидается тот же номер2, теперь в фактическом numeric формате.
Это исправления новой приёмки; старые tests не изменялись и критерии сохранности
данных/завершения save не ослаблены.
Добавлены явные Darwin skip guards к новым native files (не runtime behavior).
Review: настоящий child os._exit73 после подтверждённого HTTP import, same Home
restart/exact SHA; точные bytes после save/reopen; startup continuous deadline/
backward/invalid clock; live component failure; accepted HTTP save и activation
store drain; unknown Thread constructor/start-before/start-after; scoped Engine
identity/read lane cap2/timeouts/borrowed connection drain.

Итоговая новая приёмка: **43 passed21.91s**; Ruff/format660 файлов green.
Общая `bash scripts/check.sh`: **4912passed +24subtests,45skipped,78warnings,
785.88s,exit0**. Все704 final hashes совпали после прогона. Предыдущие690 отличаются
только тремя разрешёнными source files. Frozen B/addendum/main acceptance/drain
acceptance exact; изменения новой preparation перечислены выше.

Read-only `.runtime/d05-06b-runtime.json` совпал с A: main V8, schema/counts
неизменны, ara_test empty, временных ara_check БД0. Row contents/секреты не читались.
HTTP bridge выделен в локальный commit **daea453**; composition/drain/result/guide
сохранены следующим локальным commit. Push/deploy не выполнялись.

Реализованы programmatic FixtureDesktop/FixtureConfig, explicit staged start,
continuous startup budget, live component monitoring, PID/strong owner/start
acknowledgement и graceful reverse-order shutdown. Добавлены LicenseClient
resources_pending/shutdown без изменения Snapshot/close semantics. HTTP reads
проверяют issued Engine identity и используют bounded source lane; legacy URL
path сохранён. Реальные HTTP/PG fixture lifecycle, save/restart/exact payload,
crash after acknowledged import и fresh online license request проверены.

Логи `.runtime/d05-06b-{red,binding-red,targeted,targeted-after-binding,targeted-final,
regression,recovery-preparation,new-final,full}.log`; manifest `.runtime/d05-06b-hashes.json`.
[Контракт](d05-06b-contract.md), [дополнение](d05-06b-api-binding-addendum.md),
[использование/ограничения](desktop-composition.md).

Это пока Mac backend integration с semantic fixture. UI/verified launcher/build,
реальный ML pack, native Windows PG/installer, signing и публичный license TLS
остаются отдельно. Full DOCX/Word parity не заявляется. По текущей команде Никиты
продолжаем следующий независимый цикл **D03-17A2b2b1** — structural move catalog,
возвращаясь к обязательной DOCX матрице; existing readers/admission guards неизменны.
Ориентир **19–29 самостоятельных циклов**, большую часть составляет DOCX; внешние
UI/weights/native release gates не включаются в обещание самостоятельного финала.
