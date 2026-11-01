# D02-07 — чтение и скачивание DOCX через локальный HTTP

30 октября 2026. Один цикл после D02-06, часть F11/F12 текущего объёма. Подключить существующее хранилище к будущему интерфейсу тремя GET-маршрутами. Это локальный технический API с прежним server-owned DocumentRuntime и local-dev контекстом, не реализация активации лицензии.

## Маршруты и данные

Маршруты устанавливаются create_app только с явно переданным document_runtime, после существующего install_documents. Без runtime остаётся прежнее поведение фабрики. Добавить install_docx_reads в новом ara.docx_documents.api; модуль и его импорт инертны, построение HTTP-схем откладывается до установки. Старые service/DTO/схема БД и маршруты неизменны.

- GET /docx-documents: JSON {"items": [summary, ...]}, через list_docx, defaults limit=50, offset=0. Ровно семь полей summary: document_id (каноническая UUID-строка), title, storage_revision (целое 1..9223372036854775807), current_sha256, current_size_bytes, created_at, updated_at (даты с часовым поясом). Нет bytes, original_sha256, owner/project или путей файлов.
- GET /docx-documents/{document_id}: тот же summary через get_docx; размер из текущих bytes. Проверка целостности обоих сохранённых файлов остаётся в сервисе.
- GET /docx-documents/{document_id}/content: точные current_data через один get_docx, без ZIP/XML-перезаписи. Content-Type application/vnd.openxmlformats-officedocument.wordprocessingml.document; Content-Disposition attachment; filename="<canonical-uuid>.docx"; Content-Length точный; ETag — current_sha256 в двойных кавычках; X-ARA-Storage-Revision — десятичная ревизия из того же snapshot. Заголовки не используют название документа. If-None-Match и Range не реализуются: всегда полный 200 для доступного файла. Cache-Control: no-store на всех трёх успешных ответах.

UUID принимается в формах Python UUID(str), невалидный путь — 422. Для списка limit — ASCII-десятичная строка в диапазоне 1..100, offset — 0..9223372036854775807; ведущие нули допустимы. Запретить знак, пробелы, дробь, exponent, Unicode-цифры, пустую строку. Ограничить длину каждой числовой строки 19 до int(). Повторы query-ключа и неизвестные query-ключи дают 422; для одиночных маршрутов любые query-ключи дают 422. Проверка запроса до обращения к сервису.

## Ошибки и совместимость

Использовать существующий DocumentError и обработчики install_documents: status/code/message/retryable/request_id, X-ARA-Auth-Mode: local-dev; уникальный UUID request_id на запрос. Ошибки валидации безопасные 422 validation_error "Invalid request". Чужой/отсутствующий документ или проект — существующая общая 404. Сбои/повреждения хранения — существующие безопасные 500/503; ошибки не включают исходный документ, SQL, имя сервера или traceback. Не ставить обработчики, меняющие старые маршруты. Не добавлять запись, импорт, сохранение, анализ или авторизацию.

Новые обработчики синхронные def, DB-вызовы исполняются штатным threadpool FastAPI, не блокируют event loop через async def. Не закрывать caller engine. Не выполнять DML; ownership/блокировки/транзакции обслуживает неизменный D02-06. Список использует metadata-only сервис. Не писать DOCX на диск и не открывать внешние ссылки.

OpenAPI описывает JSON summary/list, query defaults/bounds, binary DOCX, безопасные ошибки 404/422/500/503. Верхняя граница BIGINT в новых схемах/query сохраняется точным JSON integer (восстановить после сериализации FastAPI при необходимости, не ломая wrapper черновиков). Использовать deferred Pydantic models только в новом HTTP-модуле при необходимости. Никаких новых зависимостей.

## Разрешённые пути и приёмка

Изменять только src/ara/docx_documents/api.py, src/ara/docx_documents/http_schemas.py (если нужен), src/ara/app.py (импорт и вызов установки), tests/docx_documents/test_http_reads.py (собственные случаи). Независимая приёмка tests/acceptance/test_docx_http_reads.py заморожена до запуска; не редактировать её, контракты, pyproject, старые тесты, runner/tasks/progress или БД из внутреннего цикла. Не читать output/, .artifact-build/ и рабочий архив пользователя.

Приёмка: точные bytes до/после service-save и нового app/engine; безопасные заголовки для Unicode/кавычек в названии; список/пагинация и изоляция проектов; невалидные запросы, ошибки хранения и повреждение; отсутствие DML; OpenAPI и неизменность прежних маршрутов. Синтетический rich-source.docx должен скачаться побайтово, поэтому новый визуальный рендер не нужен: этот цикл не изменяет документ. Полный bash scripts/check.sh обязателен. После одного цикла остановиться. HTTP-импорт/сохранение, файловые диалоги, редактор, таймер и полная совместимость Word остаются дальнейшей работой.

## Согласованное исключение после реализации

30 октября 2026, прямое разрешение Никиты в чате («Да, давай») после объяснения конфликта: добавить ровно три DOCX-адреса в ожидаемый набор `tests/documents/test_http_boundaries.py::test_explicit_runtime_keeps_health_and_openapi_inert`. Все прежние адреса и утверждения сохраняются, проверка остаётся строгим равенством наборов. Это разрешение на конкретное обновление исторического теста снаружи внутреннего цикла; независимая приёмка D02-07, критерии runner и его статус не меняются.
