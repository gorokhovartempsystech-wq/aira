# D04-02 — сервер активации и проверки лицензий

4 ноября 2026. [Контракт](d04-02-contract.md) выполнен. Отдельная PostgreSQL18
схема хранит HMAC ключа, настраиваемый срок, состояние и одно устройство. Первая
активация атомарно фиксирует начало/конец; повтор после потери ответа сохраняет
срок. Одновременная активация разных устройств даёт одного победителя. Check
не активирует/не продлевает. Disabled/expired/неподготовленная БД дают отказ.

Добавлены два ограниченных HTTPS-scope POST, явные операторские init/issue/
enable/disable/serve, конфигурация только из secrets.env при явной загрузке.
Нет публичной выдачи ключей, plaintext ключей в таблице/логах, implicit init или
изменения локального editor app. Все SQL tables явно public, catalog resolution
закреплена; сторонняя одноимённая схема не подменяет лицензию. [Руководство](license-server.md).

Freeze94559eb:38 cases; red13failed/25errors2.34s, targeted38passed3.14s.
371d2f6 добавил independent shadow-schema test. Подготовка rollback test уточнена:
matcher теперь учитывает public-qualified INSERT. Все прежние assertions
сохранились (AST comparison); смысл аварии и требование atomic rollback прежние.
Совместно с54 unchanged core cases: **93passed3.38s**.

`bash scripts/check.sh`: **4195passed,41skipped,24subtests,79warnings**,exit0,
662.54s. Ruff/format green;570 gate hashes unchanged; все561 предыдущих source/
tests/config unchanged. Main `0008_docx_edit_drafts`, schema/counts unchanged;
ara_test пустая, temporaryDB0. Артефакты `.runtime/d04-02-{red,targeted,regression,full}.log`,
`d04-02-hashes.json`, `d04-02-runtime.json`.

Это локальная серверная приёмка на disposable БД. Публичный сервер не развёрнут,
production ключей не создано; HTTPS ASGI tests не являются реальной проверкой
TLS-развёртывания. Клиент/устройство/сохранение активации и desktop guard ещё нужны.
Состояние disabled запрещает следующий запуск, не обещает немедленно оборвать
уже разрешённый локальный сеанс. Привязка штатного клиента не равна аппаратной
аттестации. Фронтенд/модель/нативная release-приёмка остаются отдельными gates.

Далее **D04-03** клиентский цикл по отдельному контракту; предварительный draft
подготовлен в .runtime, source/acceptance ещё не реализованы. Ориентир
**15–30 самостоятельных циклов**, D04-02 вычтен один раз. Текущая Astra,
продолжаем по команде Никиты без остановки и без внешней публикации.
