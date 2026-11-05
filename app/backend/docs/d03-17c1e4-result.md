# D03-17C1E4 — parent fixture driver Windows

3 ноября 2026, Sol6.1 High, по [контракту](d03-17c1e4-contract.md), acceptance freeze `a919098`, source `43b5f8f`. **E4 завершён в доступных на Mac границах:** гонка подготовки теста исправлена, итоговый targeted/full gate прошёл. Native Windows acceptance остаётся открытой; C1E целиком и production Windows runtime этим результатом не принимаются. Следующий шаг — [проектирование C1F на Astra6 High](d03-17c1f-preflight.md).

Добавлены шесть новых modules: public `windows.driver` и private actor state/models/launch/control/data. Factory-only PID-bound capability, inert imports, preallocated holder, startup admission gate, три I/O owners и один strongly retained attempt. Stop coalesced/out-of-band, renew — одна команда/provisional receipt/caller acceptance с50ms policy, old L не оживает. Data pump передаёт run только после permit/armedEOF, обрабатывает partial writes и строгие events/status EOF. Candidate собирается из request/transport/retained process/Job/time proofs; reply явно fixture, без B1/SQL success.

Physical cleanup, resource closure и SQL ACK различаются. Close имеет один общий caller timeout; uncertain cancel/create остаётся на исходном owner с strong retention и closeFalse. Late Stop/expiry отзывает candidate. Natural completion может закончить ещё не принятый renew как finished/False без расширения L и без искусственного timeout. Новых SQL/API/startup/dependencies нет, caller slot не освобождается. Production Windows wiring и durable restart recovery остаются C1F gate, real weights/adapter — C2.

## Проверки

- Red до source:29errors/13native skips,0,22s, отсутствующий driver; collection42cases и новая acceptance зафиксированы отдельным commit.
- E1–E3 regression: **195passed/26native skipped**,0,33s; старые source/tests unchanged.
- Собственные E4 edges: **37passed/2native skipped**,7,07s. Real Python actor threads с проверкой owner, caller/receipt/Stop barriers, pending cancellation retention, caps и partial request, unknown/failed create, Thread.start uncertainty, clock/privacy/inert imports.100 sequential synthetic attempts не оставили actor threads. Native G death и100driver HANDLE/thread stress подготовлены, требуют Windows.
- Промежуточный full2ноября:3508passed+24subtests/39skipped,74warnings,412,98s,exit0; `.runtime/d03-17c1e4-full-check.log`. Два native-only own tests тогда добавлены после collection и проверены отдельно; итоговый прогон ниже уже включает их.
- Итоговый targeted E4 после исправления3ноября: **66passed/15native skipped**,7,91s; `.runtime/d03-17c1e4-finalization-targeted.log`. Тест повторного renew дополнительно прошёл **10/10 изолированных запусков**, `.runtime/d03-17c1e4-finalization-stability.log`.
- Итоговый `bash scripts/check.sh`3ноября: **3508passed +24subtests,41skipped,74warnings,401,07s,exit0**; Ruff/format437files прошли. Лог `.runtime/d03-17c1e4-finalization-full-check.log`. Все41 skips требуют Windows; это не successful native acceptance.

После итогового прогона **все468 code/test/contracts/runner/config файлов** совпали по SHA-256 с его стартовым baseline. Относительно начала завершающего цикла изменён только acceptance file: одна строка ожидания и форматирование двух imports; все44 существующих assert statements совпали по AST. Source, остальные tests, criteria и timeout values неизменны. UTF-8, относительные ссылки и `git diff --check` прошли.

Read-only start завершающего цикла совпал с предыдущим E4 final, итоговый final — со start: V8 `0008_docx_edit_drafts`, schema/counts неизменны, `ara_test` пуста, временных check databases нет. PostgreSQL оставлен работающим. Содержимое документов/архив, секреты, Word и weights не читались. Чужие README/spec/backlog/research/defense/output изменения сохранены. Runner/tasks/progress, DDL и остальные frozen tests не менялись. Нет push/публикации.

## Исправление подготовки теста

`test_renew_full_receipt_and_busy_control_independent_of_request` сразу после первого renewTrue начинает следующий renew и ожидает admission. Но E4 §4 прямо разрешает краткий False/busy до того, как control owner снимет уже принятый command. В первом targeted run это дало1failed/28passed/13skipped; в полном прогоне scheduling оказался другим и тест прошёл. Это известная нестабильность примера, не повод менять корректную семантику driver или скрывать initial failure.

После описанного запроса Никита3ноября дал команду «продолжи». Добавлена подготовленная строка перед вторым renew: `until(lambda: obj._state.command is None)`. Прежние assertions по двум первым permits, pending write, busy refusal, timeout, hard Stop и отсутствию ложного ACK сохраняются. Ruff дополнительно потребовал упорядочить две существующие import строки в native test того же файла: только форматирование, без изменения assertions/fixtures. Точная граница записана в [preflight](d03-17c1e4-implementation-preflight.md); остальные frozen tests не разрешено менять. Source не подгонялся под ошибочное ожидание. Первый targeted failure сохранён выше как история; устранение известной гонки проверено targeted,10изолированными запусками и итоговым full.

Следующий шаг **Astra6 High для C1F exact design** (SQL lifecycle/durable crash fence/recovery), [handoff](d03-17c1f-preflight.md), без преждевременного production wiring. Native Windows/VM-crash/suspend, external Job/descendant-limit cases, настоящий ML/Word/frontend и поставка ещё не подтверждены. Самостоятельный остаток **26–41 цикл**: завершён уже учтённый E4; новых ID/циклов не добавлено. Оценка не гарантированный потолок, внешние gates не объявлены выполненными.
