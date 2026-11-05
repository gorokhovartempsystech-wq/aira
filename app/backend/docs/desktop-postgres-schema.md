# Подготовка локальной схемы документов

D05-05D1, 4 ноября 2026. Этот этап выполняется после owned PG ready и до
создания HTTP/analysis runtime. Он не открывает доступ по лицензии, не возвращает
живой Engine и не заменяет владельца HTTP/PG.

`SchemaPreparation(home,cluster,migrations=trusted_path)` создаётся без IO.
`start()` запускает работу, `view()` отдаёт frozen phase/error_code/resources_pending.
`ready` означает, что V13 и локальная identity проверены, SQL/файловые ресурсы уже
известно закрыты. `receipt()` возвращает installation/user/project UUID, PG system
identifier/OID и revision `0013_docx_review_preferences`. Receipt — metadata, не
разрешение на доступ; Home и cluster должны по-прежнему быть open/ready.

`shutdown(timeout=5)` с0..5секунд только запрашивает Stop и ждёт worker. False
означает незавершённые либо неподтверждённо закрытые ресурсы. До отправки COMMIT
Stop приводит к rollback своей transaction после возврата SQL; после COMMIT
durable proof позволяет повторить проверку. Вызов после ready возвращает True и
сохраняет receipt. Unknown Thread.start/SQL close/Engine.dispose/native close
удерживает strong process claim до выхода процесса; force kill/retry numeric FD нет.

Alembic использует process-global context, поэтому только одна активная подготовка
допустима в процессе, включая разные Home. Native journal owner защищает от другого
процесса; SQL try advisory lock — от конкурирующего schema writer. Home/cluster
borrowed: caller закрывает их только после завершения подготовки.

## Схема и данные

Первый запуск разрешён только для пустой application schema и подходящей provenance.
Существующие migrations, локальные user/project из Home и singleton analysis fence
создаются в одной transaction. Имя внутреннего проекта — AIRA; пользовательского
аккаунта/логина это не добавляет. Fence получает installation UUID, clean/revision2.
Нет `create_all`, implicit settings/secrets, floating head или нового SQL URL из env.

Private `Home/backups/schema` содержит initializing.json и ready.json с exact
Home/PG identity/revision. Публикация no-replace, private600, fsync/F_FULLFSYNC;
parent/root nofollow/private700. Это служебные записи, без текста документов.
Другие backup siblings и закрытый postgres layout не меняются.

Оборванная первая transaction повторяется по initializing intent. После COMMIT
ACK-loss уже созданные V13/seed проверяются и публикуется ready, без повторной
инициализации. Ready с потерянными таблицами или отсутствующий ready при существующей
рабочей schema даёт recovery_required: нельзя подменить потерянную рабочую область
пустой. Повреждённые/чужие published records сохраняются; только truncated initial
temp в pristine journal и совершенно пустой SQL schema может быть создан заново.

На повторе проверяются revision, closed table inventory, columns/PG types/nullability,
PK/FK, отсутствие неподдержанных пользовательских namespaces/functions/views/types/
triggers/rules и Home user/project/Fence binding. Документы, черновики, результаты,
revision/owner_epoch и armed/drained fence не меняются. Физическое recovery анализа
выполняет supervisor, не schema bootstrap.

## Сроки и ограничения

connect2s, statement60s, lock1s, общий continuous budget120s с учётом сна компьютера.
Последняя проверка deadline/Stop выполняется и после cleanup до выдачи ready.
Неизвестное завершение native/SQL операции не выдаётся за закрытие. Диагностика
фиксированная, без SQL/paths/содержимого. Environment libpq defaults отвергаются
по наличию, их значения не читаются. Config/Alembic получают явное соединение;
cwd, environment и logging configuration процесса не меняются.

Нужен доверенный установленный каталог migrations; проверку immutable payload/
подписи предоставляет installation/launcher. Модуль не исполняет произвольный
пользовательский код. Структурная проверка не обещает обнаружить любые ручные
изменения SQL expressions/ACL владельцем компьютера.

Старый/будущий revision возвращает `schema_upgrade_required` и остаётся неизменным.
Backup/upgrade — следующий отдельный этап. Main development V8 не принимается за
пользовательскую установку и не мигрируется. Native приёмка здесь — macOS PG18.6;
Windows и общий desktop launcher остаются самостоятельными gates.

[Контракт](d05-05d1-contract.md), [фактический результат](d05-05d1-result.md).
