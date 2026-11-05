# D03-17C1D2 — результат разбора конфликта остановки

1 ноября 2026, Astra6 High, по прямому запросу Никиты. Подготовлено [нормативное дополнение D2](d03-17c1d2-stop-addendum.md). **Архитектурный конфликт разрешён; исправление runtime ещё предстоит.** Исходный frozen contract/tests `9afce73` и все12 macos source files (в том числе8 untracked WIP D2) сохранены побайтово.

## Принятое решение

Общий sticky `OwnedChild.fault` сохраняется, но перестаёт автоматически означать hard fault guardian. Добавляются отдельные readonly signal_error/hard_fault и фиксированная диагностика errno. EPERM/ESRCH/EINTR именно из signal path создают signal_error; неожиданные ошибки сигнала и самостоятельные protocol/clock/kqueue/FD/wait faults остаются hard faults.

Обычный Stop + exact terminal wait без lost ownership/hard fault дают stopped, даже если signal_error остаётся True. Без wait — никакого closed/cleanup proof. Hard fault при подтверждённом выходе — crashed; поздний Stop его не маскирует. После Stop или signal error clean невозможен. Номер74 не получает специального разрешения и не доказывает причину exit.

В дополнении зафиксированы точный pure classifier API/таблица, порядок считывания evidence после poll и final drain, запрет обратного открытия signals/повтора kill, отмена ещё не завершённого bootstrap, границы SQL/UI и additive acceptance. Отсутствие ACK/GO после уже принятой отмены не становится самостоятельным сбоем; известный malformed token/прочий hard fault сохраняется. C1A/B, wire/DDL и правило удержания slot до physical+SQL завершения не меняются.

Изменение касается трёх явно перечисленных неоднозначных положений D2/C1D; frozen baseline не переписывается. Следующий implementation применяет дополнение и сохраняет прежние tests, включая нынешний failing Stop. Подготовлена матрица новой `tests/acceptance/test_docx_analysis_macos_stop_outcome.py`: freeze/red до source changes, детерминированные cut points и native повторения. Дополнительных бизнес-вопросов или смены формата IPC для этого не требуется.

## Проверка этого прохода

**`bash scripts/check.sh`:1 failed,3192 passed +24 subtests,75 warnings,361,74s,exit1**; Ruff/format390files прошли. `.runtime/d03-17c1d2-stop-design-full-check.log`. Неизменённый WIP всё ещё падает на `test_native_stop_independent_of_model_request` (crashed вместо stopped). Это ожидаемый незакрытый implementation defect, не зелёный gate и не готовность D2. Новых production tests в design-cycle нет.

Проверка предложенной таблицы охватила192 комбинации W/L/H/R/S и code=None/0/74/-15/-9/76: нет closed без proof, нет clean при Stop/signal error, hard fault не маскируется. `.runtime/d03-17c1d2-stop-design-table.json` — только логическая проверка проекта, не приёмка будущей реализации. SHA256 сравнение подтвердило неизменность source и frozen D2 contract/acceptance; relative links/UTF-8/git diff --check проверены.

Read-only `d03-17c1d2-stop-design-start-runtime.json`/`-final-runtime.json` совпали с baseline D2: main V8/schema/counts unchanged, ara_test пуста, временных ara_check0. Пользовательские строки/документы не читались, secrets/archive/Word/real model не использовались. PG оставлен запущенным. Чужие dirty документы и untracked материалы сохранены. Только собственные design/status docs включаются в локальный commit; D2 WIP source не публикуется и не входит в verified code commit. Runner/tasks/progress/dependencies unchanged.

## Следующая команда

**Сейчас вернуться на Sol6.1 High: завершить D03-17C1D2 по дополнению Stop**, затем продолжать D3 отдельным циклом по прежней договорённости. Начать с additive acceptance/freeze/red, исправить обе агрегации fault и сопутствующее состояние bootstrap, проверить остальные незавершённые части WIP, targeted/native/full gate, baseline/result/local commit. Не начинать D2 заново и не ослаблять existing tests.

Последний полностью проверенный implementation остаётся **D1 `2d93304`**. Самостоятельный остаток **29–44 цикла**, D2 ещё не вычтен; этот разбор не добавляет новый этап в счётчик. Windows/real model/suspend/frontend/полный DOCX/Word/лицензирование/поставка остаются за границами данного уточнения.
