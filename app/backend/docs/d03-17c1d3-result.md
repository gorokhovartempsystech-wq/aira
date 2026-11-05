# D03-17C1D3 — parent transport и candidate proof

2 ноября 2026, Sol6.1 High, после D2 `706cefb`. **D3 завершён**, выполнен [контракт](d03-17c1d3-contract.md). Acceptance freeze **c707da1**, red12failed,0,11s,exit1; исходные D1/D2/C1A–C1C tests/source/contracts сохранены.

Четыре новых source files: explicit fixture driver, независимый bounded control writer, один nonblocking data pump и immutable metadata view. Request/spec/identity/budget проверяются и отделяются до launch; большие frames не занимают mutex Stop. Служебный armed+EOF обязателен до записи request. Permit seq/PIPE_BUF/total caps, late renewal/clock rollback/expiry/backpressure fail closed; нет queue permits или новых300s.

Transport candidate выдаётся только после valid ready/stages/result+events EOF, closed(clean,0,True)+status EOF, normal/reaped G exit0 и live local budget без Stop/fault. Никакого success по DTO/status/result frame отдельно. Fixture bytes по-прежнему `fixture-response`, **не реальный B1 анализ**; D3 не вызывает SQL/C1A или существующий unguarded completion. Caller C1F сохранит собственные publication fences.

Stop/close/renew отделены от data decode/IO. Close не освобождает caller slot и не подтверждает неизвестный physical child exit. Смерть G оставляет blocked/cleanupFalse; inherited M slot может жить до естественного выхода bounded fixture. После смерти S guardian получает EOF и прекращает M независимо от GIL. В этих тестах прямые дети reaped владельцами; при намеренной смерти владельца bounded orphan освобождает slot после своего выхода и OS reaping, PID не ищется и не используется для kill.

Targeted/own **21passed**,13,82s,exit0, `.runtime/d03-17c1d3-final-targeted2.log`. Native success/error/nonzero/tail/flood/result+hang,8MiB blocked request+Stop, explicit renewal/local invalid inputs, G death+slot hold, abrupt S death, forged apparent success через valid closed+G exit77, atomic control EAGAIN/short write/512cap, clock rollback, inert import/private metadata. Повторные закрытия без FD/thread growth и освобождение decoder buffers проверены отдельно. Native cases не skipped; fixture не объявлена ML/Windows proof.

Предварительный full `.runtime/d03-17c1d3-full-check.log` дал3245+24,exit0, но **не используется как итог**, поскольку во время него добавлены исправления освобождения protocol buffers и natural close с двумя новыми own checks. **Окончательный `bash scripts/check.sh`:3247 tests +24 subtests passed,76 warnings,401,62s,exit0**, Ruff/format398files прошли, `.runtime/d03-17c1d3-final-check.log`. Source/tests совпали с final-start hash snapshot.

Read-only `d03-17c1d3-start-runtime.json`/`-final-runtime.json` совпали: main V8/schema/counts unchanged, ara_test пуста, временных ara_check0. PG оставлен запущенным. Секреты/архив/Word/реальный engine/пользовательские документы не использовались. Старые source/tests/DDL/runner/tasks/progress/dependencies и чужие dirty материалы сохранены. Только свой проверенный код/тесты/статусные документы в локальном commit; публикация/push не выполнялись.

## Передача C1E и границы

После зелёного D3 Mac transport/guardian завершены в пределах synthetic C1, не real desktop/analysis. C1F scheduler+SQL recovery, C2 engine adapter/weights, DOCX/Word, license/установщики/frontend и физический suspend ещё впереди.

Следующий **C1E требует точного Windows ownership/IO проекта на Astra6 High**: общий C1 пока оставил выбор atomic Job assignment при creation либо verified suspended-create/assignment handoff, исключающий неуправляемый startup gap. Нужны exact process/Job/pipe HANDLE ownership и inheritance, cleanup при assignment/Resume failure, Stop при EOF/close, физический proof по retained handles/active count, Win continuous clock и bounded pipe transport. POSIX PIPE_BUF/kqueue/Darwin binding не переносить на Windows по догадке. Native Windows gate обязателен и недоступен в текущей Mac среде; mocks не заменяют его. После законченного точного контракта возвращаться на Sol6.1 High для реализации/доступных проверок.

После завершённого D3 самостоятельный остаток **27–42 цикла**, без работы Ани/Артёма. Уточнение C1E пока не разбивает этап на дополнительные строки и не увеличивает оценку заранее. D3 не публикуется автоматически в GitHub, готовность Windows/пилота не заявляется.
