# D05-02 — владение локальным HTTP-сервером

4 ноября 2026. [Контракт](d05-02-contract.md), freeze **f12a53b**. Реализован
LoopbackServer с exclusive app/client ownership, native ephemeral loopback,
strict same-loop ASGI lifespan, bounded body prefetch и graceful HTTP drain.
[Интерфейс оболочки и ограничения](desktop-server.md).

Начальная приёмка: **1failed,35errors**,1.00s — отсутствовала реализация server.
После реализации **36passed**,2.55s. Дополнительно15 review cases: независимые
конфликты app/client, quarantine после failed cleanup, detached connection,
ошибка создания/старта потока, большой integer timeout, Windows socket fixture,
неправильные/повторные lifecycle acknowledgements, SystemExit/early serve exit,
ожидание finally после shutdown.complete. Совместный targeted контур с D05-01
и лицензированием: **360passed,2skipped**,11.29s. Замороженные assertions не менялись.

Сервер не принимает второй start, не закрывает чужой LicenseClient при конфликте,
не публикует ready после startup timeout/stop. До inner API полностью проверяет
ограниченное body; отдельный Stop не занимает ordinary lane. Уже принятый HTTP/SQL
не отменяется по caller timeout. Shutdown ждёт HTTP, затем app lifecycle/finally;
пока завершение не подтверждено, возвращает False. Ошибки протокола не считаются
чистым завершением, соответствующие объекты остаются quarantined.

Реальный HTTP/macOS и disposable PostgreSQL: остановка во время editor save
возвращает pending; после снятия задержки save завершается200, DOCX/current revision
сохранены, original не изменён. Аналогично проверено ожидание synthetic HTTP write.
License transport/identity/clock в этих tests synthetic; настоящие веса не запускались.

`bash scripts/check.sh`: **4462passed,43skipped,24subtests,80warnings**,
668.46s,exit0. Ruff/format green. Все606 final hashes и594 previous hashes
совпали. Основная БД `0008_docx_edit_drafts`, schema/counts прежние, ara_test пустая,
temporaryDB0. Логи `.runtime/d05-02-{red,targeted,regression,full}.log`,
hashes `d05-02-hashes.json`, snapshot `d05-02-runtime.json`.

Ограничения: компонент не включает frontend, непереданный DOM/IME buffer, autosave,
PostgreSQL bootstrap/миграции, supervisor/model composition, установщик или public
license deployment. Windows option fixture не заменяет native Windows запуск.
Host pending относится к его HTTP/lifespan/socket; старый DNS worker лицензии может
доживать по D04-03. Неуспешный app cleanup не обходится новым host в том же процессе.

Следующий **D05-03** — проверяемый состав immutable installation
payload: pinned manifest, runtime/PG/frontend/model inventory и explicit fixture mode.
Это основа дальнейшего автоматического запуска/сборки; новых продуктовых функций нет.

Ориентир **12–27 самостоятельных циклов**; D05-02 вычтен один раз. Текущая Astra,
продолжаем без переключения режима. Production/ML/frontend/native Windows gates
не объявляются закрытыми по числу пройденных тестов.
