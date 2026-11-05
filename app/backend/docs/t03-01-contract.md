# T03-01: неизменяемые ревизии решений

Первый из трёх циклов T03: сохранить выбор групп и изменения текста предложения, прочитать текущий выбор и историю. T03-02 добавит preview и проверку применимости, T03-03 — атомарное apply. В этом цикле документ и результат анализа не меняются; нет ML, UI, ответов на вопросы или новых версий документа.

## Решения как черновик

Для каждой change_group храним `decision`: pending (ещё не выбрано), accepted, rejected или deferred. pending отличается от явного deferred. PUT заменяет полный снимок решений: каждая группа исходного результата присутствует ровно один раз. Пустой результат допускает decisions=[].

Accepted — намерение пользователя, не факт применения. Можно сохранить принятые группы с вопросами, непринятыми зависимостями и конфликтующие альтернативы: черновик не обязан быть применимым. Эти ограничения проверит preview/apply. Сохранение не убирает blocking_question_ids, не меняет change_outcomes и не принимает зависимости автоматически. Решения по findings и ответы на questions вне этого цикла.

Редактируются только тексты new_blocks в существующих patches. Состояние каждой группы:

```json
{"group_id":"g1","decision":"accepted","edits":[{"patch_index":0,"new_block_index":0,"text":"Точный новый текст\r\n"}]}
```

Индексы — настоящие int >=0, не bool/float/строки; относятся к исходному неизменяемому результату. Каждая пара индексов внутри группы уникальна. Нельзя менять operation/target/kind, число и порядок блоков, evidence, зависимости или вопросы. В delete_block нет редактируемых new_blocks. Edits можно хранить и при pending/rejected/deferred. Пустой text допустим как в NewBlock.Text; Unicode сохраняется дословно, NUL и суррогаты запрещены. Никакой trim/нормализации текста или ID.

## HTTP

Ровно один новый путь `/runs/{run_id}/review`: GET и PUT. Маршруты подключаются только с явным DocumentRuntime; health-only и local guard сохраняются. Старый RunResponse из 14 полей не меняется. Используется прежний безопасный error envelope и X-ARA-Auth-Mode.

GET без query возвращает последнюю ревизию, HTTP 200. Если ревизий нет, возвращает виртуальную revision_number=0 с revision_id/parent_revision_id/created_at=null и всеми группами pending, edits=[]. GET ничего не записывает. Optional query `revision_id=<UUID>` возвращает конкретную сохранённую ревизию этого run; неизвестная/чужая ревизия даёт одинаковый 404/not_found.

PUT принимает ровно три обязательных поля:

```json
{"expected_revision_id":null,"expected_result_fingerprint":"<64 lowercase hex из GET review>","decisions":[{"group_id":"g1","decision":"accepted","edits":[]}]}
```

expected_revision_id — UUID строкой или null для первого сохранения. fingerprint — SHA-256 канонического JSON сохранённого AnalysisResult (`json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")`), не вычисляется из решений. Он связывает решение с увиденным результатом; run отдельно связывает его с базовой версией и контекстом. Backend возвращает fingerprint из GET review. Все поля strict/extra=forbid на каждом уровне; все поля групп/edits обязательны. Верхняя граница API: <=5000 решений, <=5000 edits суммарно, <=1_000_000 символов суммарно в text. Чужой owner/revision ID, готовый patch или source result не принимаются как поля тела.

Успешный PUT и его точный повтор возвращают HTTP 200. GET/PUT имеют один ReviewResponse с полями ровно:

- run_id, document_id, base_version_id, context_revision_id — UUID строкой, из сохранённого run;
- execution_mode=`fixture`;
- revision_id, parent_revision_id — UUID строкой или null (parent null у первой/виртуальной);
- revision_number — int >=0;
- created_at — timezone-aware timestamp или null только у виртуальной;
- result_fingerprint — 64 lowercase hex;
- decisions — полный снимок в порядке change_groups исходного результата; edits отсортированы по (patch_index,new_block_index).

Число полей — 11. В ответе нет owner, ключей, source result/документа, служебного SQL. Исторический ответ сохраняет свой ID/parent/номер/время/решения и не становится новой ревизией при чтении.

## Доступ, готовность и ошибки

GET и PUT проверяют актуальный Project.owner_id == runtime.user_id, Document.project_id == runtime.project_id и AnalysisRun.owner_id == runtime.user_id. Неизвестный/чужой run даёт одинаковый 404/not_found до проверки готовности, fingerprint или истории. Новый владелец проекта не получает контекст и решения прежнего создателя. Project/Document фиксируются блокировками на время операции; порядок согласован с worker, исключающий цикл ожиданий.

Только succeeded разрешает review; queued/running/failed дают 409/review_not_ready/false. Повреждённый сохранённый request/result/несовпадение внутренних IDs — безопасный 500/storage_error/false, не пользовательский 422. Проверить validate_result с сохранёнными request и importer flag; дополнительно соответствие request/result run_id, document_id, base_version_id, context_revision_id самим полям AnalysisRun, включая mode. Содержимое результата не менять.

Допускается review по прежней базе, даже если current_version_id документа изменился. В ReviewResponse явно остаётся исходный base_version_id; скрытого rebase нет. Конфликт текущей версии проверит preview/apply.

Ошибка формы/неизвестные или повторные group IDs/пропущенные группы/невалидные индексы/лимит текста — 422/validation_error/false. Несовпадение expected_result_fingerprint с текущим результатом — 409/review_result_changed/false. Если сохранённая ревизия уже существует и fingerprint её результата отличается от текущего валидного result, GET/PUT дают тот же 409, не переосмысливая старые edits относительно нового payload. Порядок: доступ → succeeded → валидация сохранённого результата и его связи → fingerprint → решения/конкуренция. Базовая Pydantic-проверка тела/UUID допустима до обращения к БД.

OperationalError →503/storage_unavailable/true; другие ошибки хранения/commit →500/storage_error/false. Сообщения постоянные, не содержат payload, IDs чужих записей, SQL, DSN, текста исключений. Ошибки не меняют ревизии или source данные.

## Конкуренция и повторы

Новая ревизия — одна транзакция с блокировкой AnalysisRun FOR UPDATE, повторной проверкой доступа и чтением текущей вершины цепочки. GET использует согласованный снимок и блокировки, не создавая строк.

expected_revision_id задаёт родителя новой ревизии; он должен совпадать с текущей вершиной (null, если ещё нет ревизий). Иначе 409/review_conflict/false. Неизвестный родитель и родитель другого run дают тот же конфликт, без раскрытия сведений. Backend назначает UUID, номер = parent.number+1 (или 1), owner из runtime, timestamp из БД.

Для безопасного повтора используется сама связь с родителем, отдельного Idempotency-Key нет. Если у указанного родителя уже есть ребёнок с тем же result_fingerprint и точно теми же каноническими decisions, вернуть именно этого ребёнка, не добавляя строку. Это работает и для первой ревизии (родитель null), и если позднее уже созданы следующие ревизии. Изменённое содержимое с тем же родителем — 409/review_conflict. Перестановка групп/edits/полей JSON не меняет содержимое; текст и выбор меняют. Одинаковое содержимое с новым ожидаемым родителем считается новым явным сохранением и создаёт следующую ревизию.

Два конкурентных PUT от одного родителя с одинаковым содержимым → два одинаковых 200 и одна новая строка; с разным → один 200 и один 409. После полного commit возвращается detached response. Сбой вставки/commit не оставляет частичной ревизии и не меняет старые снимки. Приложение никогда не UPDATE/DELETE старые ReviewRevision.

## Схема 0004_review_revisions

Добавить только новую миграцию revision=0004_review_revisions, down_revision=0003_worker_execution. В AnalysisRun добавить только именованный UNIQUE(id,owner_id), без изменения существующих полей/ограничений. В ara.models зарегистрировать ReviewRevision:

- id UUID PK, created_at TIMESTAMPTZ NOT NULL DEFAULT now();
- run_id UUID NOT NULL, owner_id UUID NOT NULL FK users.id;
- составной FK (run_id,owner_id) → analysis_runs(id,owner_id);
- parent_revision_id UUID NULL;
- revision_number INTEGER NOT NULL CHECK>0;
- result_fingerprint TEXT NOT NULL CHECK ровно 64 lowercase hex;
- decisions JSONB NOT NULL CHECK array;
- UNIQUE(run_id,revision_number), UNIQUE(run_id,owner_id,id), UNIQUE(run_id,owner_id,parent_revision_id);
- составной FK (run_id,owner_id,parent_revision_id) → review_revisions(run_id,owner_id,id);
- CHECK parent_revision_id<>id; CHECK (revision_number=1) = (parent_revision_id IS NULL);
- partial UNIQUE INDEX на run_id WHERE parent_revision_id IS NULL (один корень); индекс owner_id.

Без каскадного удаления. Старые таблицы и строки сохраняются. Повторный upgrade ничего не меняет; downgrade удаляет только review_revisions и добавленный UNIQUE AnalysisRun; повторный upgrade возможен. У AnalysisRun нет изменяемого current_review_id: вершина читается по наибольшему revision_number под блокировкой run. SQL-инварианты обеспечивают принадлежность, один корень/одного ребёнка и уникальность номера; точный последовательный номер проверяет приложение.

## Приёмка и scope

Независимая приёмка использует синтетические succeeded результаты, включая зависимости/вопросы/альтернативы, и реальные PostgreSQL в своих ara_check_<uuid>. Проверить полный снимок/историю после нового engine, точность текста, неизменность run/result/context/version/attempt, прежнюю базу, owner isolation/transfer, read-only virtual review, strict shape и ссылки, гонки/replay от старого родителя, отказ записи/commit, invalid stored result, schema/history up/down. Оригинальный рабочий архив не использовать.

Разрешены src/ara/reviews/**, src/ara/models.py, src/ara/app.py, migrations/versions/0004_review_revisions.py, tests/reviews/**. Не менять analysis_contract, runs, worker, документы/версии, старые миграции, зависимости, независимую приёмку, runner/задачи/журнал. Parent до цикла дополняет OpenAPI-test новым путём и фиксирует исторический migration-test T02-03 на 0003. Общий gate bash scripts/check.sh. Остановиться после T03-01.
