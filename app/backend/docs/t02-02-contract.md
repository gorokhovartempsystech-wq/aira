# T02-02: сохраняемые задания анализа

Добавить создание/чтение задания Linting/Merge и неизменяемого снимка контекста. Этот цикл сохраняет только queued; worker, lease, результат анализа, повторы выполнения и ML относятся к T02-03. Не менять контракт анализа 0.1.0, предыдущую миграцию и поведение документов.

## HTTP

Маршруты подключаются только в create_app(document_runtime=...). Автономный health-only и запрет локального режима вне local сохраняются. Используются прежние middleware local-dev и безопасный error envelope.

POST /documents/{document_id}/runs, обязательный единственный заголовок Idempotency-Key. Ключ — 1..128 ASCII-символов из [A-Za-z0-9._:-], без trim; отсутствующий, повторённый или невалидный заголовок → 422. Body содержит ровно mode (lint/merge), base_version_id (UUID строкой), context_items (массив объектов id/role/text). Все поля обязательны. ID и тексты не нормализуются; для UUID допустимо каноническое строковое представление в ответе/отпечатке.

Context items соответствуют модели контракта: уникальные непустые ID, role new_requirement/user_clarification/reference, точный Unicode без NUL. На границе этого API: <=100 элементов, ID <=200 символов, непустой после strip текст каждого элемента и суммарно <=1_000_000 символов текста. Lint запрещает new_requirement, merge требует хотя бы один. Проверка непустоты не меняет сохранённый текст. Лишние поля (owner, run_id, status, result, blocks, execution_mode и т.д.), числа вместо строк, неверные UUID/тип массива → безопасный 422/validation_error/false.

Создание и успешный повтор возвращают 202 с одинаковым RunResponse. GET /runs/{run_id} возвращает 200 с тем же RunResponse. Поля ответа ровно:

- run_id, document_id, base_version_id, context_revision_id — строки UUID;
- mode: lint/merge; status: queued (схема может перечислять будущие running/succeeded/failed); execution_mode: fixture;
- created_at — timezone-aware timestamp;
- request — сохранённый AnalysisRequest 0.1.0;
- has_import_omissions — сохранённый backend bool.

В ответе нет результата/оценки, ключа идемпотентности, fingerprint или сведений других владельцев. Fixture обозначает выбранный будущий адаптер, не факт выполнения анализа. GET не запускает работу. OpenAPI содержит оба маршрута и модели тела/ответа. Существующие маршруты сохраняются.

## Доступ и снимок

Каждый POST/GET проверяет runtime.project_id и актуальный Project.owner_id == runtime.user_id, принадлежность документа этому проекту. Для POST base_version_id должен принадлежать именно этому документу; можно выбрать прежнюю версию, совпадение с current_version_id не требуется. GET дополнительно требует AnalysisRun.owner_id == runtime.user_id (здесь owner_id фиксирует создателя задания).

Недоступный/неизвестный документ, версия, задание или несоответствующий owner проекта → одинаковый безопасный 404/not_found, без раскрытия текста и ID. Проверять доступ к целевому документу/версии до возврата replay/conflict. При смене владельца проекта прежний пользователь теряет доступ, новый не получает приватные контексты/задания прежнего создателя.

Backend создаёт run/context IDs и собирает AnalysisRequest из сохранённых блоков выбранной версии и переданного контекста, затем вызывает существующий validate_request. В snapshot run_id/version_id/document_id/context.revision_id точно соответствуют сохранённым сущностям. Ни один ID владельца или block payload не принимается от клиента.

Unsupported исходные блоки сохраняют id/kind, но для analysis request их text заменяется фиксированным описанием `[Unsupported block retained in source version]`: оригинал остаётся в DocumentVersion. has_import_omissions=true, если в версии есть import_omissions или хотя бы один unsupported-блок. Поддержанные блоки и context text сохраняются дословно. Повтор/GET возвращает сохранённый snapshot, не пересобирает его из текущей версии. Невалидные внутренние данные версии → безопасный 500/storage_error, без частичной записи.

## Идемпотентность и транзакции

Ключ уникален в рамках owner_id для операции создания задания, включая разные документы/проекты. Fingerprint — SHA-256 канонического JSON `{document_id, mode, base_version_id, context_items}`: `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")`, UUID в каноническом строковом виде. Ключи объектов сортируются, порядок массивов/ID/текст сохраняется. Server IDs, timestamps, текущая версия и Idempotency-Key в fingerprint не входят. Одинаковый ключ+тело → прежний run/context и 202, включая после перезапуска; другой payload → 409/idempotency_conflict/false без старого ответа/ID/текста.

Одной транзакцией: проверить/зафиксировать границу доступа (Project FOR SHARE; документ нельзя переместить во время операции), проверить точную версию, проверить ключ; затем создать ContextRevision и AnalysisRun с snapshot и статусом queued, commit до ответа. Engine принадлежит вызывающему коду, Session создаётся на операцию. История документов не меняется.

UNIQUE(owner_id,idempotency_key) обязателен в БД. При гонке одного ключа проигравшая транзакция откатывается целиком, включая свой context. Только нарушение соответствующего именованного unique constraint разрешает безопасное повторное чтение победителя в новой транзакции с новой проверкой доступа. Никакого catch-all IntegrityError→replay или бесконечного повтора создания. Два одинаковых concurrent запроса → один run/context, два одинаковых 202; разные тела → один 202 и один 409. Разные владельцы используют одинаковый ключ независимо.

Отказ сохранения context/run или commit не оставляет частичных записей. OperationalError → 503/storage_unavailable/true; другие ошибки хранения → 500/storage_error/false. Ошибки не содержат SQL, DSN, payload, key и чужие данные. Созданный до неопределённого сетевого исхода run находится повтором по тому же ключу; не обещать автоматическую обработку без worker.

## Схема и миграция

В ara.models зарегистрировать ContextRevision и AnalysisRun в существующем Base.metadata. Добавить только `migrations/versions/0002_analysis_runs.py`, revision=0002_analysis_runs, down_revision=0001_initial_documents. Старую миграцию и схему четырёх таблиц T01 не менять.

context_revisions: id UUID PK, created_at timestamptz default now, document_id FK documents, owner_id FK users, items JSONB NOT NULL с CHECK array; UNIQUE(document_id,owner_id,id).

analysis_runs: id UUID PK, created_at timestamptz default now, owner_id FK users, document_id FK documents, base_version_id UUID NOT NULL, context_revision_id UUID NOT NULL, mode TEXT NOT NULL CHECK lint/merge, status TEXT NOT NULL DEFAULT queued CHECK queued/running/succeeded/failed, execution_mode TEXT NOT NULL DEFAULT fixture CHECK fixture, idempotency_key TEXT NOT NULL, request_fingerprint TEXT NOT NULL CHECK ровно 64 lowercase hex, request_payload JSONB NOT NULL CHECK object, has_import_omissions BOOL NOT NULL DEFAULT false. Ограничение длины idempotency_key 1..128; именованный UNIQUE(owner_id,idempotency_key). Составные FK (document_id,base_version_id)→document_versions(document_id,id) и (document_id,owner_id,context_revision_id)→context_revisions(document_id,owner_id,id). Индексы для document_id/owner_id/context_revision_id и очереди (status,created_at); без каскадного удаления истории.

Повторный upgrade ничего не меняет. Downgrade до 0001 удаляет только две новые таблицы, сохраняя старые данные; повторный upgrade возможен. Импорт моделей не открывает БД. Миграции не запускаются автоматически в приложении.

## Приёмка и scope

Независимые тесты на собственных ara_check_<uuid>: миграция с сохранением старых данных, схемные ограничения, HTTP snapshot после new app/engine, old base version, owner isolation/transfer, replay/conflict, гонки, полный rollback, invalid input и безопасные ошибки. Старые проверки metadata/head сохраняются; список OpenAPI дополняется двумя маршрутами до запуска.

Разрешённые пути: src/ara/runs/**, src/ara/models.py, src/ara/app.py, migrations/versions/0002_analysis_runs.py, tests/runs/**. Не менять analysis_contract, документы/предыдущую миграцию, независимые тесты, runner, зависимости/launcher, задачи/критерии. PostgreSQL уже запущен; общий gate bash scripts/check.sh, стандартное разрешение на сокет допустимо. Остановиться после T02-02.
