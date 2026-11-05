# D03-17E3 — HTTP фильтров, скрытия и представления результата

3 ноября 2026. Самостоятельный цикл F08/F09 после проверенного E2B (4609b9a).
Контракт и приёмка фиксируются до source/red. Настоящей модели нет; fixture
обязателен в ответе, native Mac проверяется отдельно, Windows gate не заявляется.

Allowed: новый `src/ara/docx_review_api/{__init__,_http,_wire,_view}.py`; только
вызов installer после routes в D `docx_analysis_api/_http.py`; только расширение
path matcher в D `_transport.py` для analysis-review/analysis-preferences.
Новые independent tests `tests/acceptance/test_docx_review_http.py` и
`test_docx_review_http_native.py`; docs contract/result/API guide/queue.
Никаких изменений E1/E2B/schema/models/old tests/runner/deps. Default create_app
без analysis_supervisor сохраняет прежние routes; explicit S устанавливает оба
API. Installer требует existing analysis service/editor/runtime, не создаёт
pool/process, не читает БД/config, не запускает S. Пул/Stop/lifespan прежнего D.
Повторный/неполный installer ConfigurationError.

## Routes / wire

Все пути `/docx-documents/{document_id}`:
- GET `/analysis-preferences`: `{schema_version,preferences}`.
- POST `/analysis-preferences`: body exactly command_id,expected_revision,
  disabled_types,show_questions,show_hidden.200 confirmed `{schema_version,receipt}`.
- POST `/analysis-runs/{run_id}/findings/{finding_id}/visibility`: body exactly
  command_id,expected_revision,result_sha256,hidden.200 receipt. Scope IDs только
  из path; finding_id=df-64lowerhex. Нет arbitrary dismissal key/apply API.
- GET `/analysis-runs/{run_id}/review`: проверенное filtered presentation.
- GET `/analysis-review`: latest successful accepted_order presentation.

schema_version=docx-review-http/1. Preferences DTO document_id,revision(decimal
string),disabled_types(sortedarray),show_questions,show_hidden. Никаких keyset,
исходного текста, внутренних SQL rows или настройки модели в metadata.
Receipt DTO document_id,command_id,kind,expected_revision,revision(strings),changed.
Это original ack команды; после старого replay UI читает свежие preferences/view,
не применяет original changed к последнему UI вслепую. Unknown COMMIT503→retry
того же body/key. Новая команда после409 должна учитывать свежую revision.

Review DTO schema_version,run(прежний D summary+error_code),preferences,view
(E1 docx-review-view/1),view_sha256,current_storage_revision,current_sha256,
matches_saved_document,fixture. view_sha256 — canonical E1 bytes, не весь HTTPJSON;
view.stored_result_sha256 — full original B1 record, его подавать в visibility.
Те же exact source ranges/fixture/no_findings rules. RAM freshness frontend
сверяет с editor отдельно. Raw D result routes остаются неизменными/unfiltered.

UUID/counters strict canonical strings; flags exactbool; unknown/duplicate keys,
query strings и GET bodies отвергать. Request≤64KiB, JSON UTF8/media/encoding
semantics D/editor; safe error envelope/requestID/local-dev/no-store. Никаких
произвольных queryfilters с обходом persistence.

## Read consistency / concurrency

GET preferences вызывает E2B get_state и не создаёт defaults. Review:
scoped V13 tx читает current preferences snapshot и successful same-doc origin,
summary. No-result404/non-success409. SQL завершается; E1 present выполняет B2
revalidation внеlock. Затем короткий scoped tx повторно проверяет ownership,
current durable DOCX revision/SHA и preference revision. Если prefs изменились
во время decode,409 preferences_conflict (без скрытого unbounded retry и без
выдачи устаревшего filterview); source изменился — matches_saved_document=false.
Не подменять pinned source на latest content. Snapshot/result immutable.

Используется тот же nonblocking D gate:2 ordinary HTTP операции,1 dedicatedStop.
Review endpoints используют свой bounded AnyIO limiter2 (не глобальную общую
очередь); shielded thread operation удерживает HTTP gate до фактического конца.
Не держать SQL locks при presentation/hide source decode. Два больших review
reads не мешают knownStop. Core E2B по-прежнему проверяет exactsource до hide.
Сбой/foreign/corruption не возвращает частичных findings и не меняет rawanalysis.
V12 сохраняет D runtime, новые feature routes отвечают safe503 без migration.

## Приёмка

HTTP native/portable save→check→GETreview→hide→reopen→showhidden→unhide; strict
transport+OpenAPI, type/question filters не меняют stored request disabled_types/
dismissed и rawresult; oldack replay неоткатываетstate; CAS/foreign/run/finding/
resultSHA guards; corrupted origin safe500; pending/non-success409; sourceedit
freshness; preferencechange whiledecode409; bounded gate/knownStop; duplicates/
large/media/body guards. Existing D/F3/E1/E2 tests unchanged, mainV8/hash safety.
Freeze/red→targeted/full→result/localcommit. Дальше E4 conservative crosssource
identity и full F09 integration; frontend Ани не объявляется реализованным.
