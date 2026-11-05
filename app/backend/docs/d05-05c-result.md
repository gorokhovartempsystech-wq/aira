# D05-05C — persistent macOS PostgreSQL bootstrap

4 ноября 2026. [Контракт](d05-05c-contract.md), freeze **8cbc5cf**. Реализованы
first initdb/постоянная БД aira, durable journal, повторное открытие по system ID/OID,
SQL readiness и graceful shutdown с сохранением принятой транзакции.
[Интерфейс и ограничения](desktop-postgres-cluster.md).

Red **29failed**,0.95s — namespace/API отсутствовал. Optional socket_id profile
extension + прежний portable профиль: **77passed**,0.07s. Initial cluster/profile
targeted **22passed**,4.08s; семь native crash cutpoints **7passed**,6.71s.
Additive damage/cleanup review **16passed**,10.76s. Дополнительный review выявил
**5failed**,62.14s: четыре документированные libpq environment defaults не были
отклонены до IO; OID требовалось повторно сверить на application connection после
maintenance observation. Исправлен source, assertions не ослаблялись. Final
combined targeted/native **50passed**,22.29s. Новые tests подготовки не исправлялись.

`bash scripts/check.sh`: **4770passed,45skipped,24subtests,79warnings**,
665.13s,exit0; Ruff/format green. Все657 final hashes совпали. Из645 предыдущих
hashes643 неизменны; два разрешённых исключения — profile `_models.py`,`_plan.py`
для optional fresh socket_id с неизменным default API. Остальные старые source,
tests/dependencies/migrations/runner не менялись.

Main `0008_docx_edit_drafts`, схема/счётчики совпали с прошлым snapshot; ara_test
пустая, temporaryDB0. Логи `.runtime/d05-05c-{red,profile,targeted,recovery,review,
review-red,regression,full}.log`; hashes `d05-05c-hashes.json`, readonly snapshot
`d05-05c-runtime.json`. Native tests только на синтетических временных PG18.6.

Не объявляются готовыми document schema/bootstrap upgrade/backup, Windows runtime,
общий desktop launcher, реальная модель/фронтенд и установщик. Следующий отдельный
цикл **D05-05D1**: current schema и stable local identity, с независимым durable
proof против повторного создания потерянной рабочей схемы. Backup/upgrade затем.
Текущая Astra подходит; продолжаем без переключения.
