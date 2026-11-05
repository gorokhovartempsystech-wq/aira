# Соединения редактора и анализатора с локальной базой

D05-06A, 4 ноября 2026. `ara.desktop.database.bind_database(home,cluster,schema=...)`
связывает рабочие SQL-соединения с уже открытой Home, готовым owned PostgreSQL и
успешным `SchemaPreparation`. URL из окружения, старые development UUID и секреты
не используются. Factory проверяет живые handles/metadata, но не открывает SQL.

`source.document_runtime()` возвращает lazy Engine и Home-derived user/project.
`source.settings()` — явные settings для существующих supervisor factories.
Supervisor требует те же installation/user/project и root `Home.analysis`.
Старые `DatabaseSettings` и development factory остаются отдельным прежним путём.

Каждое новое DBAPI соединение получает закрытый профиль socket/role/database и
options. До передачи приложению проверяются actual PG system identifier, database
OID, PG18/role/synchronous_commit, revision13 и Home scope. Собственная read probe
откатывается. Замена базы на пустую по тому же адресу не проходит эту проверку.
Миграций, seed или восстановления данных bridge не выполняет.

## Завершение работы

1. Закрыть допуск новых HTTP-запросов и дождаться ранее принятых операций.
2. Завершить supervisor и дождаться его SQL/native cleanup.
3. Вызвать `source.shutdown(timeout=...)`,0..5секунд. До True сохранять Home/PG.
4. После известного завершения Source можно останавливать PG и закрывать Home.

Source запрещает новые подключения после Stop, но не отменяет уже выданный SQL
connection и не прерывает принятую transaction/COMMIT. При False нужно дождаться
возврата существующих connections либо сообщить о неподтверждённом cleanup.
Повторная остановка относится к тому же source; новый source на Home запрещён,
пока прежний claim не освобождён.

Desktop engines используют NullPool. После каждого checkin драйвер закрывает
native connection, idle SQL connections не удерживаются. Максимум4 документных
соединения и по1 на admission/control/publication supervisor; превышение даёт
`database_busy` без новой очереди. Это технический concurrency budget.

`view()` возвращает frozen phase,error_code,connections,connecting,resources_pending.
ready означает открытый metadata binding, а не проверенный healthcheck без SQL.
resources_pending остаётся True, пока source открыт, даже при нулевых счётчиках;
closed/False появляется только после явного known shutdown. Счётчики отражают
зарегистрированные raw objects и незавершённые создания, включая quarantined outcomes.

Если driver.close выбросил исключение, одного raw.closed=True недостаточно:
драйвер может установить этот признак до завершения native finish. Source сохраняет
raw/claim и состояние failed/cleanup_unknown. Повторного native close нет. Это
проверяется независимо от того, подавил ли SQLAlchemy исключение DBAPI при checkin.
Ошибка native creation с неизвестным исходом также сохраняет pending claim;
обычный отказ до открытия соединения не создаёт фиктивный незавершённый native ресурс.

## Ограничения

Home/cluster/schema остаются borrowed. Caller обеспечивает их жизнь дольше Source
и соблюдает порядок shutdown. Source и полученные engines используются в исходном
процессе; Source API проверяет PID до своих mutex и не копируется/сериализуется.
Не передавать Engine/DBAPI connections через fork. Изменение схемы параллельно
редактору не поддерживается; D1 проверяет структуру до открытия приложения.

Нет чтения секретов, implicit settings, DDL, аккаунтов, UI, лицензирования или
автоматического запуска HTTP в этом bridge. Native приёмка — macOS и явно учебный
semantic fixture; это не подключение реальных весов модели и не Windows release.
Полный desktop launcher/установщик выполняются следующим этапом.

[Контракт](d05-06a-contract.md), [результат проверки](d05-06a-result.md).
