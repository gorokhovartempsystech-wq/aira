# Постоянная локальная PostgreSQL — macOS

D05-05C, 4 ноября 2026. Инфраструктурная БД `aira`, PG18, auth peer текущего
OS-пользователя. Продуктовая схема и desktop composition подключаются отдельно.

`PgTools(target,postgres,initdb,control)` — immutable metadata трёх проверенных
бинарников из одного bin directory. Не доказательство подписи/неизменности: caller
обязан предоставить trusted installation. Поддержаны macos-arm64/macos-x86_64;
Windows implementation здесь отсутствует.

`ClusterRuntime(home,tools)` не выполняет IO при создании. `start()` запускает
background worker; frozen `view()` возвращает phase/error_code/resources_pending.
Только `ready` разрешает `connection('aira'|'postgres')` и `identity()`. Connection
metadata не содержит пароля и не разрешает HTTP API до отдельного schema gate.
`identity()` содержит installation UUID, PG system_identifier, application database
OID и major18. Home borrowed: закрывать его после cluster, не наоборот.

`shutdown(timeout=5)` принимает конечные0..5секунд и возвращает True только при
подтверждённом закрытии всех своих ресурсов. False требует ожидания, а не force kill.
Приложение сначала завершает HTTP/analysis/pools, затем cluster, затем Home.
Уже открытая SQL-транзакция может завершить COMMIT при Stop: используется smart
shutdown owned foreground PG через D05-05B. Unknown native/SQL close/thread outcome
сохраняет strong claim до выхода процесса. Самопроизвольный выход PG снимает ready.

## Первый запуск и восстановление

В Home/postgres сохраняются private durable journal records:

1. `initialization.json` — намерение создать первый cluster этой установки.
2. `.data18.pending` — initdb с fsync/checksums и reject-auth до создания auth profile.
3. `prepared.json` — независимый system_identifier после проверки PG18 control
   metadata; затем no-replace rename в `data18`.
4. Exact `server.conf`, `pg_hba.conf`, `pg_ident.conf`; foreground PG на новом private
   `/private/tmp/aira-pg-<random UUID>`; SQL profile/identity verification.
5. Создание `aira`, только если подтверждено незавершённое первое создание.
   `cluster.json` фиксирует OID уже существующей БД; matching temporary proof удаляется.

Каждый запуск имеет новый socket directory: существующий сервер на старом endpoint
не может пройти новую readiness-проверку. В рабочей установке missing/replaced `aira`,
changed system ID/OID/config, missing record/data и неоднозначный journal дают
`cluster_recovery_required`; пустая БД вместо прежней не создаётся. ID проверяется
на maintenance connection и повторно на фактическом application connection.

При incomplete initdb и valid initial intent без prepared/final/data исходный stage
целиком сохраняется как `failed-init-UUID`, затем разрешён новый initdb. До3 retained
attempts; дальше ошибка восстановления. Никакого recursive удаления. Корректные
metadata temps публикуются с теми же bytes. Обрыв initial temp исправляется только
в совершенно пустом layout; другие повреждённые temps сохраняются для recovery.

Private directories700, metadata600/single-link; nofollow pins и closed layout.
До изменений нужны runtime owner и свободный inherited process slot. Existing
published metadata/config не переписываются. Atomic publication использует
Darwin no-replace rename, fsync и F_FULLFSYNC. При обычном завершении удаляется
только собственный пустой socket directory после подтверждённого выхода PG.

## Ограничения и диагностика

- Общий startup budget120секунд, включая сон компьютера; connect2секунды,
  statement2секунды и lock500мс. Срок просит graceful Stop; зависший native call
  остаётся pending до реального завершения, не объявляется закрытым.
- Известные libpq environment overrides отвергаются по наличию до изменений файлов.
  Их значения не читаются/не печатаются; global env не изменяется. Источник списка:
  [официальная документация PG18](https://www.postgresql.org/docs/18/libpq-envars.html).
  Production launcher должен запускать Python с узким окружением.
- `pg_controldata` используется для ограниченных identity fields, не как отдельное
  доказательство CRC integrity. Полный stdout не публикуется: обязательны реальный
  PG startup и SQL observation. PG stdout/stderr обрабатываются владельцем процесса.
- Прежний профиль задаёт passfile=/dev/null; libpq может выдать фиксированное
  предупреждение о типе файла. Секреты пользовательских pass/service files не нужны.
- Native subprocess tests выполнены на временной PG18.6/macOS, не на профиле
  пользователя. Main development V8 не мигрируется этим runtime.
- После аварийного выхода приложения старый private socket directory может
  остаться. Новый запуск его не усыновляет и не удаляет; отдельной уборки orphan
  каталогов нет. Потеря guardian с живым потомком удерживает slot, PID-adoption/kill
  отсутствует. Внешнее ручное вмешательство в PG не является supported recovery.
- Нельзя считать готовыми schema upgrade/backup, Windows lifetime, UI launcher,
  реальную модель, подписанный установщик или выпуск продукта.

Приёмка и фактические результаты общего прогона: [контракт](d05-05c-contract.md),
[результат](d05-05c-result.md).
