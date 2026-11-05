# D03-17D — API проверки сохранённого DOCX

3 ноября 2026. Следующий независимый цикл после C2 review fixture; относится к
F06–F08/F10/F12. Веса модели пока не предоставлены, настоящий ML остаётся отдельным
gate C2. Этот цикл соединяет уже готовые editor/Supervisor/SQL и учебный native
режим. Не меняет Word readers, модель, фильтры/скрытие (E), лицензию или desktop
provisioning. На выбранной Astra продолжаем без паузы.

## Подключение и владение

Новый namespace `ara.docx_analysis_api/`: `__init__.py`, `_service.py`, `_reads.py`,
`_wire.py`, `_http.py`, `_transport.py`. В `ara.app.create_app` единственное
расширение — optional keyword `analysis_supervisor=None`; его установка требует
document_runtime и уже установленного app-owned EditorRegistry. По умолчанию
старые routes/поведение неизменны. Existing tests не редактируются.

Explicit installer проверяет issued Supervisor, совпадение server-owned
user/project/database с DocumentRuntime/registry; чужой/повторный installation
отвергается ConfigurationError. Не принимать supervisor, scope, execution/model
или пути из HTTP. Factory/installation не запускают runtime, не мигрируют/не
provision DB и не читают конфигурацию. Bootstrap владеет start/shutdown; тесты
запускают S явно. Local-dev label сохраняется, настоящая авторизация/лицензия не
заявляется. Новый service/registry не заменяет существующий editor.

## Запросы и ответы

Все пути имеют `/docx-documents/{document_id}`. UUID canonical; counters —
canonical decimal strings без bool/negative/leading zero. JSON≤64KiB,
duplicate/unknown keys, query strings, лишние GET bodies и неподдерживаемые
media/encoding отвергаются существующей bounded transport semantics. Ответы и
ошибки no-store. OpenAPI явно описывает request/response и pending semantics.

| Метод / suffix | Смысл |
|---|---|
| POST `/analysis-runs` | client_request_id + SavedCheckCommand без document_id (он из path). Provider получает exact SavedTarget через app registry.saved_target с save command/counters. Нет latest-content lookup вместо сохранения |
| POST `/analysis-runs/{run_id}/retry` | Только client_request_id; новый run по pinned source предыдущего terminal run, не по изменившемуся current |
| GET `/analysis-requests/{client_request_id}` | RAM admission receipt, либо durable scoped run по тому же key после eviction/restart |
| POST `/analysis-requests/{client_request_id}/stop` | Пустой JSON object; быстрый Stop известного issued ticket без ожидания SQL/публикации. Для неизвестного активного run после restart — recovery_required, не произвольный process kill |
| GET `/analysis-runs/{run_id}` | Scoped durable metadata: status/stage/error/timestamps/source/provenance; не запускает inference |
| GET `/analysis-runs/{run_id}/result` | Только source-verified success; non-success409 result_not_ready, отсутствующий/чужой404 |
| GET `/analysis-result` | Latest successful accepted_order; новый failed run не скрывает прежний success; если success отсутствует404 |

POST может вернуть202 **до durable enqueue**. Это принятое намерение со стабильным
client_request_id, run_id=null, phase=admitting; не подтверждение записи БД.
Location ведёт на analysis-requests/key. GET там же показывает phase
admitting/queued/active/settling/finished/not_admitted, known run_id, local
stop_requested/stop_reason и последний подтверждённый SQL state. Не выдавать Stop
intent за cancelled. not_admitted содержит safe error_code; fresh explicit POST
того же не принятого key может повторить admission. Same registered key + exact
command возвращает прежний ticket; другой command409. После durable terminal
replay не читает actor/provider и не повторяет inference.

Metadata DTO `schema_version=docx-analysis-http/1`, fixture=true для учебного S.
Decimal counters, timestamps ISO UTC, UUID strings. No settings/paths/SQL/trace/
native handles/raw buffers. GET durable request не восстанавливает прежнее RAM
полномочие на launch/Stop. Результат только подтверждённый SQL, не candidate из
процесса. Неизвестный COMMIT сохраняет pending, пока F3 не согласует исход.

## Очереди, scope и Stop

HTTP не вызывает B3 start/старый complete/cancel напрямую: admission и Stop идут
через один S. Новый key проходит current document scope check перед регистрацией;
source callback выполняется только в F3 admission lane. Existing cache сохраняет
exact command digest. Replay durable terminal работает и после истечения editor
session. Не держать mutex сервиса во время SQL/provider/codec/native calls.

Cache максимум17 active/in-flight +128 terminal metadata entries. Terminal LRU
можно вытеснить (durable fallback); pending/unknown нельзя. Concurrent same-key
registration хранит placeholder + command digest и coalesced stop intent, после
возврата issued ticket Stop доставляется вне lock. Known negative admission можно
повторить только новым явным POST. Cache не хранит DOCX/response payload.

Отдельные nonblocking HTTP gates: до2 обычных запросов,1 stop. Ожидающих очередей
HTTP tasks нет; excess503 analysis_busy. Native Stop известного ticket не ждёт
SQL gate/парсинга результата. При unknown key допустим scoped read, но он не
создаёт ticket/новый epoch. Никакой claim/resume старого running после restart.

Scope проверяется в scoped SQL read project→document. Cached admission/Stop
относится только к документу и owner, ранее принятому этим S; ни чужой ключ, ни
подмена path не дают доступ к ticket. При передаче ownership SQL terminal logic
F3 сохраняется; старый процесс можно остановить по уже выданному ticket, но
выдача result всегда заново проверяет текущий scope.

## Чтение результата

Read helpers используют explicit runtime, bounded DB transactions, не меняют
run/result/source/ledger. Читают SourceBundle/AttemptBundle/ResultBundle под
project→document scope, затем тяжёлый `restore_result` вне locks. Corrupt
hash/source/request/result —500 storage_error, без частичной выдачи замечаний.
После decode короткий scope recheck перед выдачей; snapshots immutable.

Public envelope исключает `private_provenance` (raw confidence/rule/suggestion)
и оставляет findings/questions/exact source ranges/coverage/provenance/counts/
no_findings. Fixture label обязателен; «нет замечаний» не выдумывается.
`stored_result_sha256` — идентификатор сохранённого полного envelope, не hash
отрезанного публичного JSON. Response включает source identity и current durable
revision/SHA, `matches_saved_document`. Это не доказательство совпадения с
несохранённой RAM-версией: frontend сравнивает её отдельно и не переносит старые
координаты поиском цитаты. Latest определяется accepted_order, не finished_at.
Никакого autofix/apply endpoint или потери предыдущего результата.

## Приёмка

Новые independent files: `test_docx_analysis_http.py` (strict transport,
конкурентный pending/replay/Stop, scope), `test_docx_analysis_result_reads.py`
(restore/corruption/latest/current identity), `test_docx_analysis_http_native.py`
(реальный editor save→native review fixture→GET result→edit/new save→repeat,
restart replay без старого actor). Synthetic DOCX, disposable V12 только.

Обязательные негативы: same key changed body, foreign doc/run/key, unconfirmed
save/stale counters, queued/active Stop, unknown enqueue ACK, DB outage при
известном Stop, corruption результатов/источника, new failure с прежним success,
limits/duplicates/content headers, no side effects import/construction,
bounded gates/no waiting queue, старые routes и все F3 cases без изменения.

Freeze/red до source; targeted и обязательный полный check; main V8/hash
сохранность/result/local commit. Runner/tasks/progress/dependencies/schema/native
contracts не меняются. После D — E filters/hide в отдельном цикле. Реальные веса/
адаптер, frontend Ани, Windows/Word/native production release gates остаются
честными внешними/зависимыми этапами, не засчитываются по fixture API.

## Уточнение wire перед freeze

Receipt: `schema_version,document_id,client_request_id,phase,run_id,stop_requested,
stop_reason,state,error_code,fixture`. `state` — null либо flat RunSummary +
`error_code`; GET run — `{schema_version,run}`. Result —
`{schema_version,run,result,stored_result_sha256,current_storage_revision,
current_sha256,matches_saved_document,fixture}`. Null означает отсутствие
подтверждённых metadata, не отсутствие операции. Поля B1 внутри `result` сохраняют
свой frozen wire type (включая source counters); counters HTTP RunSummary — strings.

Отдельный lazy read pool2/max_overflow0/pool_timeout0.5 с supervisor SQL timeout
options создаётся только explicit installer, без соединения. App lifespan
закрывает только этот pool. S и editor живут по прежнему ownership. Не меняет
общий runtime engine или PostgreSQL settings глобально. Timeout/OperationalError
выдают safe503; остальные ошибки safe500. HTTP gate охватывает весь запрос;
threadpool-вызов shielded, чтобы отмена HTTP не освободила слот раньше операции.

При mismatch body известного key HTTP409 до нового admit. После eviction/restart
проверка command выполняется durable admission; возможен202 с последующим
not_admitted/conflict. Это не обещание успешного enqueue. Finished replay в RAM
не вызывает provider; durable replay выполняет только scoped SQL lookup.
