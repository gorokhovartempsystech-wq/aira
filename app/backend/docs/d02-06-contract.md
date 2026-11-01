# D02-06 — хранение и восстановление DOCX

29 октября 2026. Один ограниченный цикл после D02-05, часть F05/F11/F12 [текущего объёма](current-product-scope.md). Пользователь попросил продолжить разработку. Сохраняем точный исходный пакет и последнюю редакцию DOCX в существующей PostgreSQL, чтобы открыть документ после завершения прежней сессии или процесса. Это отдельный адаптер хранения, без преобразования в Markdown.

## Границы и API

Добавить `ara.docx_documents`, модель `DocxDocument` и миграцию `0006_docx_documents`. Существующие Markdown-документы/версии/черновики и чистые DOCX-модули не менять. Нет HTTP, UI, файлового диалога, записи пользовательского .docx по пути, таймера автосохранения, восстановления вкладок/анализа/скрытия замечаний, шаблона, новых документов без исходника или истории сохранённых редакций. Использовать существующие зависимости; новых не добавлять.

Публичный пакет экспортирует `StoredDocx`, `DocxSummary` и функции:

```python
import_docx(runtime: DocumentRuntime, *, document_id: UUID,
            title: str, data: bytes) -> StoredDocx
get_docx(runtime: DocumentRuntime, *, document_id: UUID) -> StoredDocx
list_docx(runtime: DocumentRuntime, *, limit: int = 50,
          offset: int = 0) -> tuple[DocxSummary, ...]
save_docx(runtime: DocumentRuntime, *, document_id: UUID,
          expected_storage_revision: int, data: bytes) -> StoredDocx
```

DocumentRuntime — существующий явно переданный контекст engine/user/project. Caller владеет engine; каждая операция владеет собственной SQLAlchemy Session и транзакцией, закрывает их и не dispose/close engine. Импорт модулей не читает файлы, секреты и не открывает соединения. Операции обращаются только к явно переданной БД; не читают файлы, не вызывают модель/внешнюю сеть/процессы, не логируют содержимое документов или SQL-параметры.

StoredDocx — frozen/slotted dataclass с полями `document_id: UUID`, `title: str`, `original_data: bytes`, `original_sha256: str`, `current_data: bytes`, `current_sha256: str`, `storage_revision: int`, `created_at: datetime`, `updated_at: datetime`. Оба bytes-поля исключены из repr. DocxSummary — frozen/slotted dataclass с полями `document_id`, `title`, `storage_revision`, `current_sha256`, `current_size_bytes: int`, `created_at`, `updated_at`. У DTO нет дополнительных полей; они отделены от ORM/транзакции, даты timezone-aware. Возвращать DTO только после успешного commit, подготовив/проверив его до commit.

## Аргументы и DOCX

document_id — UUID-объект, не строка. title — настоящий str, 1–200 Unicode code points, не только whitespace, без NUL и суррогатов. Сохранять название точно, не strip/normalize. data — настоящий bytes, не bytearray/memoryview. expected_storage_revision — настоящий int без bool, от 1 до 9223372036854775806 включительно. limit — настоящий int 1–100, offset — настоящий int 0–9223372036854775807. Неверные скалярные аргументы дают существующий `DocumentError(422, "validation_error", "Invalid request", False)` до доступа к БД.

Входные bytes import/save проверить существующим `project_docx` **до доступа к БД**, используя фиксированные defaults DocxLimits()/ProjectionLimits(). Пустой/невалидный/превышающий лимиты пакет сохраняет DocxError/ProjectionError и безопасный code; неверный тип data относится к validation_error выше. Байты сохранять буквально, без перепаковки, нормализации, принятия revisions или изменения свойств Word. Структурно читаемые защищённые документы сохранять можно: запрет правок остаётся в редакторе.

Storage API в этом цикле не принимает собственные limits. Более широкие лимиты чистой сессии не расширяют пределы этого адаптера. Это технические границы текущей реализации, а не новый продуктовый предел длины документа.

## Доступ, чтение и список

Доступ определяется только существующими Project.owner_id и runtime.user_id/project_id. У новой записи нет отдельного owner_id. Project FOR SHARE с проверкой владельца удерживается до commit/rollback. Далее get/replay берут DOCX-строку FOR SHARE, save — FOR UPDATE; запрос обязательно ограничен id и текущим project_id, состояние после ожидания блокировки должно быть актуальным. Порядок Project → DocxDocument не менять.

Для отсутствующего/чужого проекта или документа — тот же общий 404/not_found/message, что `documents.storage._not_found()`. Доступ проверяется до проверки сохранённого содержимого, import conflict или CAS. Передача проекта новому владельцу передаёт доступ, прежний его теряет; перемещение записи в другой проект требует runtime этого проекта. Это сохранение технической области доступа, не реализация продуктовых аккаунтов.

get возвращает исходный файл и текущий черновик, не создавая/обновляя строк. При get, save и replay импорта проверить оба сохранённых пакета тем же bounded project_docx и соответствие обоих SHA-256 реальным bytes, а также форму метаданных DTO. Повреждённая сохранённая запись даёт 500/storage_error и не ремонтируется автоматически. Это выявление повреждения, а не криптографическая защита от владельца БД, способного вручную поменять и данные, и hash.

list возвращает только текущий проект, `created_at DESC, id DESC`, с limit/offset. Новый пустой проект даёт tuple(). Операция не выбирает BYTEA в результат SQL и не строит проекцию для каждого документа; размер берёт через octet_length(current_data). Проверяет форму возвращаемых метаданных, но не обещает валидность пакетов до get. Старые таблицы документов в этот список не смешивать.

## Импорт и сохранение

document_id генерирует caller до первого импорта и использует как ключ повтора. Новый ID позволяет намеренно импортировать второй экземпляр тех же bytes. Первый import создаёт одну строку: original_data == current_data == вход, оба SHA вычислены из bytes, storage_revision=1. title и original_data/original_sha256 через этот сервис впоследствии не изменяются.

Если тот же ID уже доступен, точное совпадение title и исходных bytes означает повтор импорта: вернуть **текущий** StoredDocx, не сбрасывать черновик, ревизию или даты. Другие title/исходные bytes дают 409/import_conflict/retryable=False. Сравнивать реальные bytes, не только SHA. Чужой ID даёт общий 404, не конфликт с деталями. Гонку первых импортов разрешить PK и INSERT ON CONFLICT DO NOTHING с последующим заблокированным чтением: два одинаковых запроса дают одну запись и один ID; разные payload дают один успех и один conflict. Внутри транзакции не оставлять aborted state после уникального конфликта.

save принимает полный текущий DOCX. После доступа и проверки сохранённой записи сверить storage_revision. Только точное равенство expected_storage_revision разрешает UPDATE current_data/current_sha256/storage_revision/updated_at. Ревизия увеличивается на 1; updated_at — DB clock_timestamp() после блокировок. Порядок записей определяется ревизией, не часами; форма метаданных не требует updated_at >= created_at. Даже одинаковые bytes с актуальной ревизией дают новое успешное сохранение; со старой ревизией всегда 409/docx_conflict/retryable=False. Два конкурирующих сохранения от одной ревизии дают ровно один успех; поздняя запись не перезаписывает новую. Нет idempotent replay сохранения по одному SHA.

Storage revision независима от session.revision и не сбрасывается после открытия документа. Сохранённые DTO допускают ревизию до 9223372036854775807 включительно: последний допустимый save MAX−1→MAX должен вернуть корректный результат, который можно читать и показывать в списке. Дальнейшее увеличение не допускается входной границей expected_storage_revision. Восстановление `DocxSession(stored.current_data)` даёт новую чистую сессию revision=0 без undo/redo; исходник продолжает храниться отдельно и не зависит от вытеснения истории сессии. Для следующих ranges используются anchors восстановленной проекции с current_sha256. После подтверждённого save внешний слой может вызвать mark_saved для сохранённой **сессионной** ревизии; если сессия изменилась, stale_revision сохраняет dirty. Этот цикл не добавляет неявный вызов mark_saved.

## Транзакции и ошибки

Одна транзакция на вызов. Ошибка подготовки DTO/SQL или commit до фактической фиксации откатывает операцию. При потере подтверждения уже выполненного commit исход может быть неопределённым: не обещать, что данные наверняка не записались, и не компенсировать запись откатом другой транзакции. Caller читает состояние и сверяет storage_revision/bytes; повтор save со старой ревизией не создаёт ещё одну запись.

OperationalError → существующий DocumentError(503, storage_unavailable, постоянное безопасное сообщение, True). Прочие ошибки хранения/повреждения/подготовки DTO/commit → 500/storage_error/retryable=False. Существующие DocumentError не превращаются в 500; ошибки входного DOCX сохраняют свой класс. Сообщения 500/503 совпадают с существующим documents.storage; для import_conflict/docx_conflict — постоянные безопасные непустые строки. Не включать SQL, DSN, title, содержимое, чужие IDs или текст исходного исключения; подавлять сырую exception chain в отображении.

## Модель и миграция

`ara.models.DocxDocument`, таблица `docx_documents`, ровно десять NOT NULL полей:

- id UUID PRIMARY KEY, без автоматического default;
- project_id UUID, именованный FK → projects.id без CASCADE;
- title TEXT, именованный CHECK char_length(title) между 1 и 200;
- original_data BYTEA и current_data BYTEA, именованные CHECK octet_length > 0;
- original_sha256 TEXT и current_sha256 TEXT, именованные CHECK regex `^[0-9a-f]{64}$`;
- storage_revision BIGINT, именованный CHECK > 0, без default;
- created_at и updated_at TIMESTAMPTZ DEFAULT clock_timestamp().

Добавить один неуникальный B-tree index (project_id, created_at, id). Соответствие hashes содержимому и полная валидация названия — в сервисе. Исходник неизменяем на уровне публичного сервиса; триггеры/роли БД для запрета ручного UPDATE не входят. Никаких дополнительных blob/history/import-key таблиц и полей; старые таблицы/ограничения не менять.

Миграция `0006_docx_documents` после `0005_document_drafts` создаёт только новую таблицу/индекс. Upgrade/repeat сохраняют девять прежних таблиц, строки, ограничения и metadata. Downgrade удаляет только новую таблицу с её индексом; выполнять в приёмке только на одноразовых БД, не на ara_dev. Перед циклом parent закрепляет три перехода исторического D01-01 migration-test на V5, не меняя assertions; актуальные head/metadata проверки сохраняются, новый тест проверяет V5→V6→V5→V6.

## Приёмка и разрешённые пути

Разрешены только `src/ara/docx_documents/**`, `src/ara/models.py` (добавить только DocxDocument и нужные imports), `migrations/versions/0006_docx_documents.py`, `tests/docx_documents/**`. Не менять старые DOCX-модули, services/routes, схемы анализа, старые миграции, зависимости, независимые тесты, runner/tasks/progress/prompt или документы.

Независимая приёмка parent фиксируется красной до запуска. Проверить точные bytes/метаданные после нового engine и отдельного процесса; import/replay без потери draft, пагинацию/изоляцию; строгие аргументы/безопасные ошибки; CAS/ABA/rollback/неопределённый commit, конкурентный import/save и блокировку доступа при смене владельца/проекта; повреждение hashes и пакетов; миграции и неизменность девяти старых таблиц. Только синтетические файлы и одноразовые PostgreSQL ara_check_<uuid>. Общий gate `bash scripts/check.sh`.

Контрольный rich-source.docx импортировать → открыть DocxSession → применить три D02-04 контрольных диапазона → сохранить → заново прочитать через новый engine/сессию. Original остаётся точным исходником, current совпадает с проверенным D02-04 экспортом, повтор импорта не теряет правки. При точном совпадении hash допустимо повторно просмотреть его сохранённый рендер bundled LibreOffice вместо повторной генерации. Word этим не считается проверенным. Не читать пользовательский архив, output/ и .artifact-build/. После одного цикла остановиться; статус и журнал пишет runner.
