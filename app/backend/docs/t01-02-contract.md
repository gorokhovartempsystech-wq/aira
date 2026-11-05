# T01-02: контракт реализации и приёмки

Это уточнение рабочей спецификации до запуска Ralph. Задача добавляет настройки, ленивое подключение и Alembic-миграции. HTTP endpoints, вход, репозитории документов, workflow версий и ML относятся к следующим задачам.

## Python API

- `ara.config.ConfigurationError` — безопасная ошибка настройки.
- `ara.config.DatabaseSettings(database_url=...)` — проверенная настройка PostgreSQL. Принимает строку или `SecretStr`; поле `database_url` предоставляет `get_secret_value()`, скрывается в `str/repr`. Пустой/невалидный URL и драйверы кроме `postgresql+psycopg` отклоняются безопасным `ConfigurationError`, без исходного URL и пароля.
- `ara.config.load_settings(*, environ=None)` — явная загрузка `ARA_DATABASE_URL`. Единственный файл настроек с секретами — `Path.home() / 'secrets.env'`; читать его только при вызове. `environ` — необязательный mapping для тестов; по умолчанию используется окружение процесса. Значение в mapping/окружении имеет приоритет над файлом, включая пустое значение (оно должно дать ошибку). Не изменять окружение процесса и не искать другие `.env`. В тестах домашний каталог подменяется синтетическим, реальный файл пользователя не читается.
- `ara.db.Base` — DeclarativeBase; `ara.db.create_database_engine(settings)` — SQLAlchemy Engine с psycopg, без подключения до `connect()/begin()`, без логирования секретов или SQL-параметров.
- `ara.models.User`, `Project`, `Document`, `DocumentVersion` — ORM-модели ниже. Импорт всех модулей инертен: без чтения настроек/секретов, создания engine и внешнего I/O. `/health` сохраняет автономность.

## Схема public

UUID — принятое техническое решение; email/пароли пользователя не добавляются до выбора входа. Все `created_at` — NOT NULL TIMESTAMPTZ с серверным default. UUID можно генерировать в Python; тесты передают их явно.

| Таблица | Поля кроме created_at |
|---|---|
| users | id UUID PK |
| projects | id UUID PK; owner_id UUID NOT NULL → users.id; name TEXT NOT NULL |
| documents | id UUID PK; project_id UUID NOT NULL → projects.id; title TEXT NOT NULL; current_version_id UUID NULL; source_url TEXT NULL |
| document_versions | id UUID PK; document_id UUID NOT NULL → documents.id; parent_version_id UUID NULL; content_markdown TEXT NOT NULL; blocks JSONB NOT NULL DEFAULT []; provenance JSONB NOT NULL DEFAULT {}; import_omissions JSONB NOT NULL DEFAULT [] |

Владелец документа определяется через проект; дублировать owner_id в документе не нужно. Индексы нужны на `projects.owner_id`, `documents.project_id`, `document_versions.document_id` (последний может покрываться составным UNIQUE).

Ограничения:

1. `UNIQUE(document_id, id)` на document_versions.
2. Составной FK `(documents.id, current_version_id)` → `(document_versions.document_id, id)`.
3. Составной FK `(document_versions.document_id, parent_version_id)` → `(document_versions.document_id, id)`.
4. Родитель не равен собственной версии. Блоки и пропуски — JSON-массивы; provenance — JSON-объект.
5. Не включать каскадное удаление истории. NULL current_version_id нужен для транзакционного создания документа, затем первой версии. Проверки доступа и прикладная неизменяемость версий добавляются в T01-03/T01-04; схема сама по себе не является авторизацией.

## Миграции

Стандартные `alembic.ini`, `migrations/env.py`, `migrations/versions/`. Никаких URL/паролей в ini. Upgrade на пустой PostgreSQL создаёт схему, повторный upgrade сохраняет её и ревизию; downgrade до base и повторный upgrade проверяются только в одноразовой базе. Миграции фиксируют DDL, а не вызывают `Base.metadata.create_all()`.

`env.py` принимает уже открытый SQLAlchemy Connection в `Config.attributes['connection']` для независимой приёмки. В этом случае не читает настройки и использует только переданное соединение. Обычный явный вызов `alembic upgrade head` загружает настройки через `load_settings()` и создаёт engine. Import приложения не запускает миграции. ORM metadata соответствует миграциям.

Механизм переданного соединения описан в [официальном рецепте Alembic](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands). Для связанных пар полей используется [ForeignKeyConstraint SQLAlchemy](https://docs.sqlalchemy.org/en/20/core/constraints.html#defining-foreign-keys); выбор полей и ограничений выше — решение этого проекта.

## Проверки и границы

Приёмка живёт в `tests/acceptance`, недоступна внутреннему исполнителю. Она создаёт новую БД `ara_check_<uuid>` в локальном project-only кластере, применяет миграции и удаляет только созданную ею БД. Существующие ara_dev/ara_test не очищаются. Недоступность PostgreSQL — ошибка проверки, не skip и не подмена SQLite.

Разрешённые пути Ralph: `src/ara/config.py`, `src/ara/db.py`, `src/ara/models.py`, `migrations/**`, `alembic.ini`, `tests/db/**`. Остальные файлы, критерии, runner, зависимости и проверки приёмки защищены. Общая команда остаётся `bash scripts/check.sh`.
