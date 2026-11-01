# T02-03: worker и тестовый адаптер

Этот цикл завершает техническую T02: отдельный worker выполняет сохраняемые задания на локальном fixture, сохраняет проверенный результат и восстанавливается после потери попытки. Реальный ML, review/preview/apply, повтор по HTTP, авторизация и Confluence не входят. Контракт анализа 0.1.0 и прежние миграции неизменны.

## Публичные интерфейсы Python

Пакет `ara.worker` экспортирует:

- `WorkerSettings(lease_seconds=30, max_attempts=3, run_timeout_seconds=900, retry_delay_seconds=1)` — frozen dataclass без I/O. max_attempts — настоящий int 1..10, остальные значения — конечные int/float (не bool): lease_seconds >0 и <=300, run_timeout_seconds >0 и <=86400, retry_delay_seconds >=0 и <=300. Ошибка конфигурации — ValueError с постоянным безопасным текстом.
- `claim_next(engine, *, settings=None) -> Claim | None`;
- `complete_attempt(engine, claim, payload) -> bool` — True только при собственном успешном commit результата;
- `fail_attempt(engine, claim, *, code) -> bool` — True только при собственном commit ошибки/повтора. Публично допустимы ровно adapter_error, adapter_timeout, invalid_result; другой code даёт ValueError до I/O;
- `run_once(engine, *, adapter=None, settings=None) -> WorkOutcome`;
- `fixture_result(request) -> dict` — чистая детерминированная функция, принимающая AnalysisRequest или dict через validate_request.

Claim — frozen dataclass: run_id UUID, attempt_id UUID, attempt_number int, request AnalysisRequest, has_import_omissions bool, lease_expires_at/deadline_at timezone-aware datetime. Это отдельно скопированные данные, не ORM/Session. Worker не доверяет полям Claim, кроме пары run_id/attempt_id для поиска своей попытки; результат проверяется по сохранённому request_payload, а не потенциально изменённому Claim.request. Engine принадлежит вызывающему коду.

WorkOutcome — frozen dataclass с полями outcome (`idle`, `succeeded`, `retry_scheduled`, `failed`, `stale`) и run_id (UUID или None). None только у idle. Adapter — вызываемый объект `adapter(request: AnalysisRequest) -> dict | AnalysisResult`; по умолчанию fixture_result. Инъекция нужна для тестов. Конфигурация CLI допускает только локальный fixture, нет параметров выбора внешнего провайдера.

## Состояния и время

HTTP создание по-прежнему сохраняет queued, attempt_count=0, без активной попытки и результата. GET и повтор POST работу не запускают. Только явный worker меняет состояния.

При первом claim фиксируются max_attempts из WorkerSettings и единый deadline_at = DB clock + run_timeout_seconds. Начало срока — первый захват, не enqueue; это позволяет обработать прежнюю очередь после обновления. Эта политика сохраняется и не продлевается последующими worker/settings. Lease новой попытки = min(DB clock + lease_seconds, deadline_at). Повтор получает новый случайный attempt_id и следующий номер; attempt_count учитывает каждую выданную попытку, даже если процесс упал до вызова адаптера.

Для времени используется PostgreSQL clock_timestamp(), считанный после получения блокировок, а не время Python, не время начала транзакции. Проверка живой попытки требует status=running, совпадение active_attempt_id, lease_expires_at > now и deadline_at > now. Равенство означает истечение. Heartbeat/продление lease в этом цикле нет.

Claim выбирает доступные queued (available_at <= now) и просроченные running через FOR UPDATE SKIP LOCKED, в порядке created_at/id. Текущие running с живой арендой и terminal-задания не выбираются. Проверка/захват и запись попытки атомарны; Claim возвращается после commit. Параллельные worker не получают один актуальный attempt.

Просроченная running-попытка получает status=expired, finished_at и error_code=lease_expired; активные поля задания очищаются. Если общий deadline истёк → failed/deadline_exceeded; иначе если attempt_count >= max_attempts → failed/attempts_exhausted; иначе создаётся следующая попытка. Исчерпанные, просроченные и потерявшие доступ задания терминализируются при проходе worker, не остаются навсегда исключёнными из выборки. При выборе queued после повтора deadline проверяется даже если available_at ещё в будущем. За один claim можно просмотреть ограниченный пакет до 100 записей, пропуская терминализированные; затем вернуть None, если живой Claim не получен. Idle означает отсутствие полученного Claim, а не отсутствие housekeeping.

Работа адаптера выполняется после commit claim, без открытой транзакции/Session. Lease ограничивает право сохранить результат, но не убивает зависший Python-вызов. Встроенный fixture конечен и не обращается к сети; для реального адаптера отдельно потребуется timeout внешнего вызова/процесса. Не добавлять поток с мнимым hard timeout.

## Доступ и запись результата

Worker — внутренний процесс, может обрабатывать разные проекты. Перед передачей снимка проверяет актуального владельца проекта документа == AnalysisRun.owner_id. При claim сохраняет текущий project_id в AnalysisAttempt. Перед complete/fail повторно проверяет владельца и тот же project_id; перенос документа между проектами во время выполнения тоже закрывает попытку. До первого claim используется текущий проект документа. Изменение current_version_id не отменяет работу по сохранённой базе.

Блокировки фиксируют Project/Document на время транзакционного перехода; повторная проверка под блокировками обязательна. Порядок блокировок должен не создавать deadlock между worker; адаптер работает без них. Если доступ утрачен до claim — failed/access_revoked без передачи payload адаптеру. Если при записи живой попытки — failed/access_revoked, попытка failed, результат отбрасывается. Если Claim уже устарел/просрочен, complete/fail возвращает False и ничего не меняет, включая error/status другой попытки.

Complete под блокировкой проверяет живую попытку/доступ, затем вызывает validate_result(payload, request=сохранённый request_payload, has_import_omissions=сохранённый bool). Непосредственно перед итоговой записью после валидации снова проверяет lease/deadline по свежему DB clock: время валидации не продлевает аренду. Сохраняются только проверенный result и вычисленный incomplete_review. Одна транзакция записывает result_payload, incomplete_review, succeeded, completed_at и завершение попытки. Ошибка валидации текущего ответа завершает попытку и задание как failed/invalid_result, без частичного результата; complete возвращает False. Старая попытка с невалидным ответом не влияет на новую.

Fail с adapter_error/adapter_timeout при оставшемся числе попыток и достаточном времени переводит задание в queued с available_at = now + retry_delay_seconds, не начиная новый вызов автоматически в той же run_once. Retry delay берётся из сохранённой текущей попытки. Если следующий момент >= deadline, итог failed/deadline_exceeded; если лимит исчерпан — failed/attempts_exhausted. invalid_result не повторяется автоматически. Attempt получает failed и исходный безопасный код ошибки; у terminal run код объясняет конечную причину. При потере доступа — access_revoked вместо ошибки адаптера.

Run_once вызывает ровно один adapter для полученного Claim. Передаёт новую глубокую копию request. TimeoutError -> adapter_timeout; другое Exception -> adapter_error; SystemExit/KeyboardInterrupt не поглощаются, аренда позволит восстановление. Невалидный ответ -> failed/invalid_result. needs_clarification — succeeded, повтор не нужен. Если запись отклонена из-за устаревания — outcome=stale. При собственной terminal-ошибке — failed, при запланированном повторе — retry_scheduled. Ошибки БД не маскируются под сбой адаптера и не запускают его повторно в этом вызове.

Все ошибки БД наружу — прежний безопасный DocumentError: OperationalError ->503/storage_unavailable/true, прочие ->500/storage_error/false, без SQL/DSN/payload/текста исключения. Сбой commit claim не вызывает adapter; сбой commit результата не оставляет частичный успех. После неопределённого commit исхода следующий worker/GET читает фактическое состояние; код не обещает ровно один внешний вызов.

## Fixture

Функция не читает файлы, примеры JSON, настройки/секреты, сеть и БД. Результат формируется для конкретных IDs, версий и строк входа. В summary явно присутствует `fixture` и пояснение, что смысл не анализировался. Никакой текст документа не выполняется как инструкция.

Coverage покрывает все входы: поддержанные блоки и непустые context — analyzed в рамках демонстрационного сценария; unsupported — skipped с явной причиной. Findings всегда пусты: fixture не делает выводов о качестве требований. Lint возвращает ready, пустые groups/questions/outcomes.

Merge: для каждого непустого new_requirement создаётся отдельная группа с одной insert_after после последнего поддержанного блока. Новый paragraph содержит точный text требования, evidence — точная цитата этого context item; outcome=proposed с нужными IDs. Это демонстрация переноса текста, не выбор правильного места или способа реализации. Если поддержанного якоря нет, на каждое непустое требование возвращается question и needs_clarification outcome, без patches; общий review_status=needs_clarification. Пустой text new_requirement (допустим базовым wire-контрактом, но не HTTP) даёт skipped coverage и out_of_scope outcome с объяснением ограничения fixture, без выдуманной цитаты. Остальные пустые context также skipped. Вход не изменяется, повтор с тем же запросом возвращает тот же dict; разные ID/версии не протекают между вызовами. Результат проходит validate_result.

## Схема 0003_worker_execution

Только новая миграция `migrations/versions/0003_worker_execution.py`, revision=0003_worker_execution, down_revision=0002_analysis_runs. Новая ORM-модель AnalysisAttempt регистрируется в ara.models. Существующие данные и поля run/context/документов сохраняются; результаты можно хранить в JSONB AnalysisRun без отдельной ORM-таблицы AnalysisResult.

Новые AnalysisRun поля:

- attempt_count INTEGER NOT NULL DEFAULT 0;
- max_attempts INTEGER NULL, deadline_at TIMESTAMPTZ NULL — фиксируются при первом claim;
- available_at TIMESTAMPTZ NOT NULL DEFAULT now();
- active_attempt_id UUID NULL, lease_expires_at TIMESTAMPTZ NULL;
- completed_at TIMESTAMPTZ NULL, error_code TEXT NULL;
- result_payload JSONB NULL (SQL NULL, не JSON null), incomplete_review BOOL NULL.

CHECK: 0<=attempt_count; max_attempts NULL или 1..10; при attempt_count>0 max_attempts и deadline_at заданы и count<=max; max_attempts/deadline_at одновременно NULL или заданы; running тогда и только тогда, когда active_attempt_id и lease_expires_at заданы (иначе оба NULL); completed_at задан ровно для succeeded/failed; error_code задан ровно для failed и только из deadline_exceeded/attempts_exhausted/access_revoked/invalid_request/invalid_result; succeeded тогда и только тогда, когда result_payload и incomplete_review заданы (иначе оба SQL NULL); result_payload при наличии — JSON object. Прежние constraints/FK/unique сохраняются. Индексы (status,available_at) и (status,lease_expires_at).

analysis_attempts: id UUID PK, run_id UUID NOT NULL FK analysis_runs.id, attempt_number INTEGER NOT NULL CHECK>0, project_id UUID NOT NULL FK projects.id, started_at TIMESTAMPTZ NOT NULL DEFAULT now(), lease_expires_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ NULL, status TEXT NOT NULL (running/succeeded/failed/expired), error_code TEXT NULL, retry_delay_seconds DOUBLE PRECISION NOT NULL CHECK>=0 AND<=300, metadata JSONB NOT NULL CHECK object. UNIQUE(run_id,attempt_number), UNIQUE(run_id,id). Составной FK AnalysisRun(id,active_attempt_id) -> AnalysisAttempt(run_id,id), named/use_alter для корректного удаления циклических FK. Индекс attempts.run_id. Каскадного удаления истории нет.

Attempt CHECK: running iff finished_at IS NULL; error_code NULL для running/succeeded, для failed/expired — один из adapter_error/adapter_timeout/invalid_result/invalid_request/access_revoked/lease_expired/deadline_exceeded. Worker формирует metadata сам: ровно adapter=`fixture`, adapter_version=`1`, model=null, prompt_version=null, model_calls=0, duration_ms=0 при старте, затем измеренное неотрицательное время по DB timestamp. Не сохранять текст исключений и непроверенные metadata адаптера. История попыток не перезаписывается новой попыткой.

Миграция поддерживает существующие queued-задания (единственное состояние, создаваемое T02-02). Upgrade повторяем, downgrade удаляет новые поля/таблицу и сохраняет старые поля и строки; старые terminal-статусы после downgrade не являются поддержанным сценарием старого приложения. Проверка downgrade выполняется с seeded queued, возвращение 0002→0003 сохраняет его ключ и snapshot.

## HTTP и CLI

Новых маршрутов нет. К RunResponse добавляются ровно attempt_count (int), result (AnalysisResult или null), incomplete_review (bool или null), error (объект code/message/retryable или null). Существующие поля сохраняются. queued/running имеют result/incomplete_review/error=null; succeeded имеет результат и bool, error=null; failed — result/incomplete_review=null, error с безопасным постоянным message и retryable=false. Служебные lease/attempt IDs, metadata, ключ и stacktrace не возвращаются. GET и replay проверяют прежние права; повтор POST возвращает тот же run с актуальным состоянием/результатом, без нового выполнения. OpenAPI содержит новые типы.

Явный `python -m ara.worker --once` выполняет run_once с load_settings() и освобождает собственный engine. Без --once опрашивает очередь до SIGINT/SIGTERM, poll delay по умолчанию 1s, можно --poll-seconds (0.01..60). CLI принимает --lease-seconds, --max-attempts, --run-timeout-seconds, --retry-delay-seconds. CLI требует ARA_ENVIRONMENT=local, не меняет настройки/авторизацию, не мигрирует БД. JSON stdout каждой активной итерации: ровно outcome/run_id, никакого документа/контекста; --once выводит также idle. Ошибки — безопасный текст stderr и ненулевой exit, без traceback секретов. Import ara.worker/__main__ не должен читать настройки/файлы/сеть; выполнение только под main guard.

`bash scripts/worker.sh --once` — локальный launcher, аналог scripts/dev.sh --documents: использует `.venv`, вычисляет собственный peer socket/ara_dev без пароля, передаёт аргументы, отказывается при явно нелокальном ARA_ENVIRONMENT. Можно отдельный scripts/serve_worker.py. Не запускает PostgreSQL/миграции и не меняет окружение родителя. Обычный запуск HTTP не запускает worker.

## Приёмка и allowed paths

До запуска parent готовит независимые tests/acceptance/test_worker_*.py, расширяет точный RunResponse в T02-02 тестах и закрепляет исторические schema-тесты T02-02 на 0002; старые head/metadata-проверки сохраняются, прежние schema-инварианты также проверяются на новом head.

Разрешены src/ara/worker/**, src/ara/runs/**, src/ara/models.py, migrations/versions/0003_worker_execution.py, scripts/worker.sh, scripts/serve_worker.py, tests/worker/**. Не менять старые миграции, analysis_contract, документы/версионный слой, API factory, зависимости, независимую приёмку, задачи, runner, журнал. PostgreSQL настоящий, тестовые базы собственные ara_check_<uuid>, архив не используется. После bash scripts/check.sh остановиться на T02-03.
