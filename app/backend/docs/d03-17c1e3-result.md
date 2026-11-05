# D03-17C1E3 — Windows Job/guardian/bootstrap

2 ноября 2026, Sol6.1 High. Реализация по [контракту E3](d03-17c1e3-contract.md), acceptance freeze `d948ca1` и user-authorized [pipe-rights addendum](d03-17c1e3-pipe-rights-addendum.md)/freeze `a32c39e`. F06–F08/F12; synthetic fixture, без реального анализа/SQL supervisor. **Available implementation завершён и проверен на Mac; native Windows gate остаётся pending.**

## Реализованное поведение

- Новый `FixtureLaunch` выдаётся до native setup, strongly retained, сохраняет caller slot reference. Его start/poll_process/finish_close принадлежат одному launch thread; request_stop разрешён другому thread. No native objects on import/prepare, нет PID recovery или automatic destructor. Повторный запуск до завершения ресурсоёмкой попытки запрещён.
- Win64 ABI и два unnamed Job: outer limit2 у S, inner limit1 у G, kill-on-close/no breakaway. JOB_LIST и explicit HANDLE_LIST при suspended create; temporary duplicates, reduced SYNCHRONIZE-only R/H у G, fixed stdio/minimal environment. Returned process/thread capabilities сохраняются до cleanup, один Resume, actual signalled wait перед exit code, signed32/259 semantics.
- Failed/created/unknown create различаются. Неизвестный исход не снимается count0/SQL/свободным slot. In-flight call сохраняет storage/Job; Stop только latch/events, никакого конкурентного close. Native error sticky, kill/close не выдаются за physical exit. Membership failure допускает cleanup exact returned process, без PID fallback/повторной модели.
- Независимые G/M entries с prepared→GO→armed, без fixture import/request до GO и полного run+EOF. G continuous clock, frozen permit sequence/binding, no late renewal, bounded IO/watchdog/diagnostic drain/status. M gate watcher начинает владеть endpoint до prepared и сам завершает pending I/O; G не зависит от model GIL. Fixture reply `b'fixture-response'` явно не B1 response.
- Новые E3 модули композиционно используют E2 pending buffers/events/endpoints. Сохраняются sticky I/O owner и strong retention до completion; parent helper не poll/close чужой endpoint. Holder True означает закрытие его ресурсов, **не** M status/SQL ACK и не result candidate. Candidate/parent driver появится в E4.
- По прямому разрешению Никиты изменена ровно одна строка E2: writer access0x40000080 вместо0x40000000. FILE_READ_ATTRIBUTES нужен GetNamedPipeInfo; FILE_READ_DATA не добавлен. Старые E1/E2 tests сохранены, новая acceptance проверяет rights и flags для synchronous/overlapped writer. Отдельный red:2failed/2native skipped до исправления.

## Приёмка

Первоначальный настоящий red E3: **9failed/21errors/1native skipped**, отсутствующие новые modules,0,22s. Freeze до source. После реализации доступны **64 новых portable passes/16 native skips**; вместе с E1/E2 targeted **195passed/26skipped**,0,30s. Raw ABI tests наблюдают flags/attribute arrays/buffer lifetime/capture-before-delete и wait-before-exit query. Lifecycle tests проверяют sticky faults/unknown, ordinary Stop до Resume, actual wait/status composition, early exit/flood, сохранность caller slot и отсутствие старого-L expiry после принятого start.

Промежуточный полный прогон до согласованного права атрибутов: **3440passed+24subtests,22skipped,76warnings,392,11s,exit0**. `.runtime/d03-17c1e3-full-check.log`, source/test hashes unchanged. Он **не final gate** после изменения E2; итоговый прогон запущен отдельно.

Final `bash scripts/check.sh`: **3442passed+24subtests,26skipped,74warnings,402,69s,exit0**, `.runtime/d03-17c1e3-final-full-check.log`. Ruff/format429files прошли. Все460files final hash baseline совпали после gate; source/tests во время/после него не менялись. Read-only final runtime snapshot совпал со start, а start — с предыдущим design final: main V8/schema/counts unchanged, ara_test пуста, временных check databases0. Первый автоматический запрос разрешения итогового read-only snapshot истёк до исполнения; разрешённый однократный повтор прошёл. Обходов нет, PostgreSQL оставлен работающим.

Старые frozen tests/DDL/wire/runner/tasks/progress/dependencies неизменны. Из прежнего source изменена только прямо согласованная строка E2. Чужие dirty README/spec/backlog/defense материалы, архив/.artifact-build/output сохранены. Секреты, реальная модель и Word не использовались. UTF-8/relative links/diff checks выполнены; локальный commit только own verified files, без push/публикации.

## Ограничения и передача

Здесь Windows не запускалась. Native Job/rights/fixture modes/guardian death/100-run HANDLE/thread tests добавлены, но на Mac skipped. Incompatible external Job/descendant-limit и physical suspend matrix дополняются в E4; mandatory pre-return crash gate требует disposable Windows VM и внешней процедуры полного cleanup. Дополнительный Job HANDLE у harness не допускается. Не выдавать новые mocks за kernel proof.

Windows production/runtime restart admission не подключены. C1F должен реализовать durable crash fence и SQL recovery; unknown create не превращается в «остановлено»/новый анализ после reaper. Root private directory пока предоставляет trusted bootstrap, installer не реализован этим этапом. Real weights/качество/новый engine contract, frontend/desktop, full DOCX/Word/лицензия остаются отдельно.

**Следующий режим: Astra6 High для точного E4 контракта**, [handoff](d03-17c1e4-preflight.md): launch/cleanup owner, control writer owner и data pump; ACK/cancel/50ms write race, bounded lifecycle и composite candidate. Затем Sol6.1 High для реализации E4. Это уже учтённый цикл, новый ID не создаётся. Самостоятельный остаток **27–42** после available E3 gate; native/team gates отдельно. Остановка после завершённого E3 только для согласованной смены режима, E4 ещё не реализован.
