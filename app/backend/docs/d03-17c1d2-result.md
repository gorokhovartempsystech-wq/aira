# D03-17C1D2 — незавершённая реализация и конфликт Stop/native fault

**Актуализация 1 ноября:** этот документ фиксирует исходный implementation failure. Конфликт уже [разрешён на Astra6 High](d03-17c1d2-stop-addendum.md), [передача на Sol](d03-17c1d2-stop-design-result.md). Runtime ещё не исправлен; исторические доказательства и результаты ниже сохраняются.

**Актуализация2ноября:** D2 [реализован и проверен](d03-17c1d2-finish-result.md), full3226+24,exit0. Ни исходный frozen тест, ни контракт не ослаблялись. Красные результаты ниже — история первого WIP.

1 ноября 2026, Sol6.1 High после проверенного D1 `2d93304`. Новый [контракт](d03-17c1d2-contract.md)/acceptance заморожены **9afce73**, red25failed,0,34s,exit1. Начаты восемь новых source files в macos; source **не прошёл gate и не включён в verified code commit**. D1/старые source/tests/контракты не менялись.

Targeted `.runtime/d03-17c1d2-targeted.log`: **24 passed,1 failed**,7,70s,exit1. Прошли token checks, scripted signal/wait sequences, normal fixture, GIL/native hang→KILL, invalid/expired/missing startup permit, malformed/missing prepared, early exit, stderr flood и result+hang. Не прошла `test_native_stop_independent_of_model_request`: ожидается stopped, получено crashed при `cleanup_confirmed=True`, child exit74.

## Конкретное противоречие

Согласованный C1D требует закрывать gate до сигналов. Watcher M на EOF вызывает safe exit74. В native Stop последовательности наблюдается: G закрывает gate → killpg(SIGTERM) возвращает EPERM → exact wait подтверждает M exit74. Исходник XNU допускает EPERM на группе без подходящих незомби-процессов; **точную причину на установленном ядре не утверждаем**. Важно, что error signal и последующий подтверждённый exit — разные факты.

При этом D2 contract требует signal-error fault latch и приоритет crashed над stopped; acceptance обычного Stop требует stopped. Копирование этого правила в код даёт неверный пользовательский исход при успешной физической остановке. Ослаблять frozen test или blanket-ignore EPERM нельзя: настоящий permission/ownership fault без exit proof должен остаться fail-closed. Выдавать clean candidate после signal fault также нельзя.

Нужно на Astra6 High уточнить, как separate native signal fault / protocol fault / Stop latch и actual wait evidence определяют **статус остановки**, сохраняя запрет новой публикации и новые spawn до physical+SQL разрешения. Возможное направление review: подтверждённый stop + конкретная signal race не обязаны означать clean success или разрешение inference; но exact правило и frozen-contract compatibility ещё не приняты. Не очищать общий fault и не менять старый C1A/B/wire по догадке.

## Доказательства и сохранность

Read-only metadata probes:8 повторов обычного Stop —7crashed/1stopped с exit74/cleanupTrue; дополнительная wrapper probe3/3crashed подтвердила ровно SIGTERM errno1 (EPERM). `.runtime/d03-17c1d2-stop-probe-entry.py` — **ignored test-only wrapper**, не production entry и не fallback kill API. Только собственные synthetic children, все G reaped/slots освобождены; ни одного retry через другой syscall/утилиту, token/DB/document data не выводились.

**`bash scripts/check.sh`:1 failed,3192 passed +24 subtests,74 warnings,655,71s,exit1**; `.runtime/d03-17c1d2-full-check.log`. Ruff/format390files прошли. Единственный failed — тот же native Stop, crashed вместо stopped. Read-only final snapshot `d03-17c1d2-final-runtime.json` совпал с start: main V8/schema/counts unchanged, ara_test пуста, временных ara_check0. PG оставлен запущенным, user data/secrets/archive/Word/real model не использовались. D2 **не завершён**; runner/tasks/progress/dependencies/старые tests unchanged.

Последний полностью verified implementation — D1 `2d93304`,3168+24. В workspace остаётся восемь untracked WIP source files D2; сохранить их для архитектурного review, не выдавать за готовый backend и не публиковать. Source D2 не включается в verified code commit. В full startup был удалён неиспользуемый пустой diagnostic loop; native child entries запускались из актуальных source с -B, ни тесты, ни поведение остановки этим не менялись. Предварительная реализация также требует обычного дальнейшего code review/own fault tests перед следующей full gate; текущие source не объявлены полностью соответствующими контракту по24 зелёным тестам.

Дальше: Astra6 High для точного уточнения этого одного D2 противоречия, затем Sol6.1 High завершает тот же цикл, без увеличения числа продуктовых функций/самостоятельных этапов. **Остаток29–44 цикла**, D2 не вычитается. Main V8, реальные веса/frontend/Windows/native Word/suspend и лицензия/desktop остаются отдельными незавершёнными частями.
