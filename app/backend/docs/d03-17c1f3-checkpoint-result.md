# D03-17C1F3 — частичный checkpoint, требуется schema design

**Актуальный итог, 3 ноября: D03-17C1F3 завершён в fixture-границах.** [Результат](d03-17c1f3-result.md):90 targeted; полный gate3706passed/41skipped/+24subtests,exit0; main V8 неизменна. Конфликт early timeout устранён additive V12 с сохранением истории и безопасным downgrade. По последней команде Никиты продолжаем на Astra без смены режима: далее C2. Самостоятельный остаток **25–40**; нижние pending-статусы исторические.

3 ноября 2026, Sol6.1 High. **F3 не завершён.** Freeze65 acceptance — `c24c428`; red до source30failed/35errors. Реализована доступная композиция supervisor/SQL/native adapters по [контракту](d03-17c1f3-contract.md), обнаружено противоречие раннего local timeout с frozen SQL constraint. [Точное доказательство и передача](d03-17c1f3-schema-preflight.md).

Новые supervisor modules выполняют explicit fixture bootstrap, пять bounded lanes, native continuous timing, scoped admission/claim/arm/heartbeat, один retained publisher, Stop/settlement/recovery/shutdown. Stable permit outcome не переписывается поздним SQL terminal. Source-backed synthetic success и настоящий Mac opaque invalid_result проверены раздельно; native Windows/real model/production provisioning и boot recovery остаются открытыми.

## Фактические проверки

- Foundation:9passed.
- Доступная композиция: **64passed,4deselected,19,35s**;61 frozen acceptance+3 own edge tests. Четыре исключения только в диагностике, критерии неизменны. Финальный лог `.runtime/d03-17c1f3-checkpoint-final-targeted.log`.
- Изолированное доказательство schema boundary:1passed,0,60s; rejected UPDATE rollback сохранил synthetic run.
- Ruff/check и format471files прошли.
- Первый полный `bash scripts/check.sh`: **1failed,3650passed,41skipped,33errors,+24subtests,76warnings,428,76s,exit1**. Primary failure — active local deadline; дальнейшие setup errors относятся только к новым F3 tests: первый незавершённый S по правилам strong registry запрещает замену. Ни одного failure/error в прежних тестах. Это сохранение fail-closed поведения, не разрешение игнорировать ошибки.
- Финальный полный `bash scripts/check.sh` по зафиксированным502 hashes: **1failed,3650passed,41skipped,34errors,+24subtests,77warnings,438,35s,exit1**. Никаких исключений. Лог `.runtime/d03-17c1f3-checkpoint-final-full-check.log`. Изменение числа setup errors относительно первого прогона связано с добавленной третьей edge-проверкой. Primary failure и все errors относятся только к новым F3 runtime/edge tests; прежние3616 tests+24subtests прошли, прежние41skips сохранены. Диагностический Green64 и обязательный красный full приведены раздельно.

До/после финального gate **502 source/test/config hashes неизменны**:483 прежних файлов,3 frozen acceptance и16 новых source/own-test files. Новые65 acceptance побайтово совпадают с `c24c428`; assertions не менялись. `.runtime/d03-17c1f3-checkpoint-{hashes,final-hashes}.json`. Рабочая `ara_dev` осталась **V8 `0008_docx_edit_drafts`**, schema/counts совпали с началом и прежним F2/F3 design baseline; `ara_test` пуста, temporary DB0. Snapshot `.runtime/d03-17c1f3-checkpoint-final-runtime.json` снят после завершения всех тестов. PostgreSQL оставлен работающим.

Собственные изменения —15 новых supervisor source modules,3 frozen acceptance,1 own edge file и5 checkpoint/status документов. Source/tests/config/migrations прежних циклов, main data, runner/tasks/progress и чужие README/backlog/spec/research/defense правки сохранены. UTF-8/относительные ссылки/`git diff --check` проверены. Локальный checkpoint сохраняется с явным **WIP** статусом; push/production startup не выполняются.

Green64 не заменяет общий gate. Early timed_out сейчас безопасно отклоняется БД; runtime прекращает compute и удерживает неподтверждённый terminal/fence, новый inference не разрешается. Подстановка будущего времени и изменение старых tests/schema не выполнялись. Не подключать partial fixture runtime как готовый продукт.

## Передача

**Astra6 High → узкое проектирование схемы local timeout и совместимости V11/F2**, затем **Sol6.1 High → завершение того же D03-17C1F3**. До исправления противоречия не переходить к C2/новым функциям и не закрывать F3. Самостоятельный остаток **26–41**, F3 не вычтен. Runner/tasks/progress не редактировались.
