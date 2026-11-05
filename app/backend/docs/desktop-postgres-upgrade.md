# Обновление локальной базы и резервная копия

D05-05D2, 4 ноября 2026. `ara.desktop.postgres_upgrade` выполняет один явно
поддержанный переход: V12 → V13 внутри уже принадлежащего приложению PostgreSQL18.
Это не импорт старой development БД и не универсальное восстановление из файла.

После `ClusterRuntime` ready, до открытия HTTP/analysis/pools:

1. Создать `UpgradeTools` с доверенными bundled `pg_dump`/`pg_restore` из того же
   bin-каталога, что и PostgreSQL.
2. Создать `UpgradePreparation(home,cluster,migrations=...,tools=...)`, вызвать
   `start()`, дождаться терминального состояния и `resources_pending=False`.
3. `ready` означает завершённое обновление с сохранённой копией; `not_needed` —
   пустую либо уже текущую схему без pending upgrade. Оба исхода требуют следующего
   `SchemaPreparation`: именно D1 подтверждает схему и identity для runtime.
4. `result()` возвращает только metadata. `backup_path()` доступен при `ready` и
   возвращает собственный archive; не передавать произвольный путь на восстановление.

Home и cluster остаются у caller. `shutdown(timeout)` принимает0..5секунд,
запрашивает остановку и сообщает, подтверждено ли завершение. При False ждать тот
же объект; нельзя перезапускать работу поверх неизвестного завершения. До COMMIT
своя SQL transaction откатывается, после COMMIT сохраняется журнал для reconcile.
Никакого принудительного завершения PostgreSQL ради timeout или автоматического
восстановления старой копии поверх новых данных.

## Какие данные сохраняются

Перед DDL выполняется полный `pg_dump --format=custom` на exported repeatable-read
снимке той же SQL transaction. Копия включает документы, исходные/изменённые DOCX,
черновики, результаты и остальные данные поддержанной схемы. SHA256 считается
потоково, проверяются размер, собственный inode, успешный exit утилит и TOC через
`pg_restore --list`. Это не полная пробная распаковка каждой копии; настоящее
восстановление в другую временную БД проверяет native acceptance.

`Home/backups/postgres/<UUID>/` хранит intent, exact старую schema receipt,
`data.dump` и backup metadata. Начатые и завершённые копии сохраняются. Успешная
копия без upgrade intent после аварии считается orphan: следующий запуск делает
новый снимок, а прежний не удаляет. По умолчанию предел16 bundles,8GiB на archive,
600секунд continuous budget. `UpgradeLimits` допускает меньшие технические пределы;
это не обещание максимального размера пользовательского документа. Size monitor
не является OS quota: при заполнении диска возможен overshoot до graceful Stop.

## Возврат после аварии

Private schema journal связывает Home, PG system identifier, database OID, source/
target revision, backup UUID/hash/size и обе schema receipts. После SQL COMMIT
новая receipt атомарно меняется местами со старой через Darwin RENAME_SWAP;
старая временно остаётся рядом и постоянно хранится в backup. Следующий запуск
либо повторяет неподтверждённую transaction, либо завершает публикацию/cleanup.

Потерянная/повреждённая копия, неизвестный revision, чужая identity, несовместимые
receipts или активный analysis fence останавливают работу с сохранением данных.
Приложение не принимает обычные записи при pending upgrade. Внешние ручные SQL
изменения в этот период не поддерживаются. Старые bundles не очищаются автоматически.

D1 и D2 используют общий процессный gate Alembic. Native owners и pinned files
защищают соответствующие каталоги, SQL advisory lock сериализует migration writers.
Unknown Thread.start/SQL/native close удерживает claim; сообщение об ошибке не
означает, что все ресурсы уже закрыты.

Это реализация macOS. Windows bootstrap/upgrade и native Windows проверка остаются
отдельной работой. V12 здесь синтетический совместимый predecessor: выпущенная
пользовательская версия V12 не заявляется. Подпись установщика, trusted payload,
реальная модель и frontend этим модулем не создаются.

[Контракт](d05-05d2-contract.md), [результат проверки](d05-05d2-result.md).
