# D04-01 — правила срока и подтверждение текущего запуска

4 ноября 2026. [Контракт](d04-01-contract.md) выполнен: pure license record,
one-device activation/check без продления при повторе, строгий ограниченный JSON,
HMAC lookup/device digest и допуск ответа только к соответствующей попытке.
Срок/nonce/device/operation/UUID проверяются, сетевое время и округление списываются
консервативно. Permission до конца срока вычисляется на переданных непрерывных
часах; библиотека сама не читает clock/сеть/секреты и не выдаёт offline authority.

Freeze2a9e2a3:54 independent cases, red6failed/48errors0.34s, targeted54passed0.07s.
`bash scripts/check.sh`: **4156passed,41skipped,24subtests,79warnings**,exit0,
665.47s; Ruff/format green. Все561 gate hashes unchanged; все555 прежних файлов
source/tests/config сохранились. Main V8/schema/counts unchanged, ara_test пустая,
temporaryDB0. Артефакты `.runtime/d04-01-{red,targeted,full}.log`,
`d04-01-hashes.json`, `d04-01-{before-runtime,runtime}.json`.

При возобновлении отсутствовал owner.json каталога сокета PostgreSQL. Read-only
проверка подтвердила владельца/права каталога, точный кластер проекта, версию18,
отсутствие TCP listener и main V8. Восстановлен только marker; scripts/БД не менялись.

Это проверенная pure основа, не серверная активация и не защищённый desktop.
TLS-подлинность произвольных bytes библиотека не устанавливает: будущий клиент
принимает ответ только от своего HTTPS-запроса. Native identity/continuous clock,
сохранение активации и запуск будут проверены отдельно. Старый development app
пока не применяет licensing guard.

Далее **D04-02**: отдельная PostgreSQL БД лицензий и серверный HTTP/API оператора,
затем D04-03 клиент. Ориентир **16–31 самостоятельный цикл**, D04-01 вычтен один
раз. Пакет ML/frontend/native release gates остаются внешними; текущая Astra,
продолжаем по последней автономной команде Никиты, без публикации.
