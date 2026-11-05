# Локальный PostgreSQL для разработки

Это самостоятельный runtime подготовки окружения. Он не реализует продуктовую задачу T01-02, миграции или хранение документов.

## Сборка

Используем официальный Postgres.app 2.9.6 с PostgreSQL 18.6, Universal (arm64/x86_64), macOS 10.15+. Полный bundle сохраняется в `.runtime/Postgres.app`, данные — в `.runtime/postgres18/data`. Всё содержимое `.runtime` исключено из Git.

- [Официальные загрузки](https://postgresapp.com/downloads.html)
- [Зафиксированный DMG](https://github.com/PostgresApp/PostgresApp/releases/download/v2.9.6/Postgres-2.9.6-18.dmg)
- [Release notes](https://github.com/PostgresApp/PostgresApp/releases/v2.9.6)

Для установки скачать этот DMG, смонтировать только для чтения, скопировать целый `Postgres.app` в `.runtime` и размонтировать образ. Не копировать только `bin`: необходимы соседние библиотеки и файлы. Глобальная установка, Homebrew и Docker не требуются.

До первого исполнения проверить подпись и допуск Gatekeeper:

```sh
codesign --verify --deep --strict .runtime/Postgres.app
spctl --assess --type execute --verbose=2 .runtime/Postgres.app
```

При отказе остановиться и разобраться с причиной. Не удалять quarantine, не отключать Gatekeeper и не переподписывать bundle. Скрипт повторно проверяет целостность подписи при `start`.

Postgres.app официально допускает другие каталоги с ограничениями: из перемещённого bundle нельзя рассчитывать на сборку расширений и линковку сторонних драйверов с его `libpq`. В проекте используется `psycopg[binary]` со своей библиотекой. [Документация](https://postgresapp.com/documentation/relocation-warning.html).

## Команды

После создания `.venv` и установки зависимостей проекта:

```sh
bash scripts/postgres.sh start
bash scripts/postgres.sh status
bash scripts/postgres.sh check
bash scripts/postgres.sh stop
```

Первый `start` инициализирует PostgreSQL и создаёт `ara_dev` и `ara_test`; последующие старты сохраняют данные. `check` выполняет `SELECT 1` в обеих БД. `stop` завершает только этот кластер и не удаляет данные. Сервер не запускается автоматически при входе в macOS. После runtime-проверок его следует остановить до фактической работы с БД.

`start` выводит каталог Unix socket и имя пользователя БД. Они нужны для настройки драйвера. TCP отключён через `listen_addresses=''`. Это не `localhost:5432`: подключаться нужно именно через указанный каталог сокета. Порт 5432 используется как часть имени сокета и не занимает TCP-порт.

Пример подключения после подстановки каталога из вывода `start`:

```python
import getpass

import psycopg

with psycopg.connect(
    host="<каталог Unix socket из start>",
    port=5432,
    user=getpass.getuser(),
    dbname="ara_test",
    connect_timeout=5,
) as connection:
    assert connection.execute("SELECT 1").fetchone() == (1,)
```

Секреты для этого локального подключения не нужны. Приложение и runtime не создают `.env`. Для будущих окружений с паролями единственным источником остаётся `~/secrets.env`.

## Изоляция и ограничения

- Peer authentication проверяет OS-пользователя; она поддерживается macOS. Это dev/test-кластер текущего пользователя, не схема production-доступов. [PostgreSQL peer](https://www.postgresql.org/docs/18/auth-peer.html).
- Сокет находится в коротком `/private/tmp/ara-pg-<uid>-<hash проекта>` с правами 0700. Короткий путь нужен из-за ограничения длины Unix socket; UID и хеш абсолютного пути разделяют проекты. Сокет и кластер имеют проверяемые маркеры владельца.
- Скрипт отказывается использовать чужие каталоги, symlink вместо runtime-каталога, другой major version или сокет, ведущий к другому кластеру. Команды сериализованы блокировкой. Каталог данных и socket lock вручную не удаляются.
- Перемещение всего проекта меняет его identity. Скрипт остановится на старом маркере; сначала остановить кластер из прежнего расположения, затем отдельно подготовить перенос. Он не усыновляет чужие данные автоматически.
- После очистки `/private/tmp` сначала выполнить `start`, чтобы восстановить каталог сокета. `status`/`stop` не создают его сами.
- В sandbox macOS может запрещать проверку подписи, проверку процесса, shared memory или Unix sockets. В таком случае команды требуют обычного разрешения среды выполнения; скрипт не обходит sandbox. Если проверка процесса запрещена, он сообщает об отказе OS, а не утверждает, что сервер остановлен.
- Обновление major version требует отдельной миграции. Не заменять bundle под работающим кластером.

## Проверено 17 сентября 2026

- Хост: macOS 26.6.1, arm64. Официальный bundle установлен только в `.runtime/Postgres.app`.
- DMG SHA-256: `9fc7d0dc08cf46dfd94bb32cbaaad81b41b37847a42d6dcb2f9fbd292813defb`. Это локально вычисленный отпечаток скачанного файла; независимая проверка происхождения выполнена через подпись и Gatekeeper.
- `codesign --verify --deep --strict` — успех; Gatekeeper: `accepted`, `source=Notarized Developer ID`. В sandbox обе проверки сначала возвращали ошибки; стандартный разрешённый вызов системных служб прошёл. Настройки защиты не менялись.
- PostgreSQL `18.6 (Postgres.app)`, Python-драйвер `psycopg 3.3.5`. Реальный `SELECT 1` прошёл в `ara_dev` и `ara_test` через драйвер; `SHOW listen_addresses` подтвердил отключённый TCP.
- Повторный `start`, `stop`, повторный запуск и проверка обеих БД прошли. Последний `status`: `stopped`; данные сохранены, сервер не оставлен работающим.
- Smoke-проверки на синтетических каталогах подтвердили отказ при чужом ownership marker и symlink вместо каталога кластера.
- Общая `bash scripts/check.sh` на момент подготовки runtime: **2 failed, 31 passed, 24 subtests passed**. Оба падения — ожидаемое отсутствие `ara.app` до выполнения T01-01; runtime не подменяет реализацию этой задачи. Эти результаты не являются актуальным статусом будущих циклов разработки.
