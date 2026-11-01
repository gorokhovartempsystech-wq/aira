# D03-16E2 — JSON HTTP и lifetime registry

31 октября 2026, после 0bd00db, Sol 6.1 High. F05/F06/F11/F12, E1 metadata-first codec. Один registry на явный DocumentRuntime приложения; health-only путь прежний. Без frontend/таймера/ML, binary/download/discard (E3), миграций рабочих баз или изменения native/storage/registry semantics.

## Routes

Префикс `/docx-documents/{document_id}`. UUID path canonical lowercase; decoded value→exact UUID через wire rules, без alias форм.

| Method/path suffix | Операция и body | 200 |
|---|---|---|
| GET /editor-recovery | inspect_recovery, no body/query | Recovery metadata |
| POST /editor-sessions | decode_open | Opened metadata |
| GET /editor-sessions/{session_id} | snapshot, no body/query | Editor metadata |
| GET /editor-sessions/{session_id}/view | один snapshot→encode_projection | Full structural view того же frame |
| POST /editor-sessions/{session_id}/commands | decode_command | Editor metadata |
| POST /editor-sessions/{session_id}/checkpoint | decode_control | Editor metadata |
| POST /editor-sessions/{session_id}/save | decode_control | Editor metadata |
| POST /editor-sessions/{session_id}/reconcile | decode_control | Editor metadata или Closed metadata |
| POST /editor-sessions/{session_id}/close | decode_control(close=True) | Closed metadata |

POST open всегда200, в том числе retry; Registry IDs/counters как E1. Никаких arbitrary operation route params/callables/user runtime. Все query params запрещены, в том числе повторяющиеся. GET body запрещён. SavedTarget/binary доступны позже E3, не base64 JSON.

## Request guard

Только application/json и optional charset=utf-8 (case/space variant как прежние paragraph routes), UTF-8 без BOM, Content-Encoding absent/identity; иной media/encoding415. Duplicate content-type/content-encoding/content-length/transfer-encoding headers422; normalization names case-insensitive. CL только bounded digits ≤19 chars, nonnegative, actual length exact; CL+TE запрещены, TE только chunked без CL. Без CL streaming chunks всё равно ограничены до extend/parse. Команды ≤8MiB body, open/controls ≤64KiB. Oversize413 editor_request_too_large; GET nonempty422. Disconnect до полного body422 без runtime dispatch. Bad UTF8/JSON/duplicate nested keys/NaN/Infinity/extra fields/counters422 без raw input в error.

Body stream/headers/query проверяются до worker. JSON decode/native mapping/runtime call/encode reply выполняются в threadpool, без блокировки event loop. CancelScope shield на worker await сохраняет ownership до выхода synchronous вызова; разрыв ответа не доказывает rollback, retry тот же command identity. Не внедрять отмену SQL/save или повторное выполнение edit.

Для новых editor-prefix paths per-app thread-safe nonblocking admission semaphore1 охватывает body read→worker→response; занятый запрос503 editor_busy/retryable=true, не dispatch-ится и не читает body. Это ограничивает одновременно удержанные входные bytes/serialized replies, дополняя registry retained budget; не hard RSS guarantee. Без global singleton, SQL/actor locks между requests. Uncertain actor attempt после завершения вызова не удерживает gate; другой документ доступен. Gate освобождается во всех paths, включая decode/native/DB/reply/send failure. Не переиспользовать asyncio lock между TestClient loops.

Каждый успех/ошибка/404/405 на новых prefix paths Cache-Control:no-store. Ошибки — прежний sanitized envelope code/message/retryable/request_id с новым server UUID, X-ARA-Auth-Mode:local-dev. Scope404/409/410/413/422/500/503 прежние, media415, busy503 отдельный code. Busy middleware самостоятельно формирует envelope до старого local-context middleware; client X-Request-ID не доверять. No body/credentials in logs/errors. Нельзя называть local-dev настоящей авторизацией.

## Installation и OpenAPI

Новый `install_editor_json(app,runtime)` в ara.docx_editor.http, deferred imports. Вызывается из create_app только при explicit runtime, после прежних installers. app.state.docx_editor_registry хранит созданный registry, app lifetime; повторная installation явно отказывает. Constructor/routes/OpenAPI не подключаются к БД/не читают secrets. Caller engine не dispose-ить. После restart новый registry/session ID, old sessions410 без переноса команды.

OpenAPI содержит девять новых path entries, body schema/required keys/command variants и errors, string-counter patterns и no BLOB JSON. Definitions могут строиться deferred helpers, но ссылки обязаны разрешаться. Прежние paths/методы/schema не удалять. Единственный разрешённый old-test edit: в tests/documents/test_http_boundaries.py test_explicit_runtime_keeps_health_and_openapi_inert добавить эти девять paths к exact expected set, все старые assertions неизменны. План E с routes уже разрешён пользователем; узкая test migration фиксируется вместе с новым acceptance до source. Другие old tests не менять.

## Пути/приёмка

Новые src/ara/docx_editor/http.py, private _http_*.py; src/ara/app.py только deferred import/install в explicit runtime branch; указанное дополнение exact path test; frozen tests/acceptance/test_docx_editor_http.py и дополнительные tests/docx_documents/test_editor_http_*.py; result docs/d03-16e2-result.md, queue, допустим link/clarification transport в d03-16-design.md. Не менять wire/runtime/native/storage/schema/dependencies/runner/tasks/progress/AGENTS.

Freeze/red до source. Real PG: полный import→inspect/open→view→commands/save/retry→close→recovery/new app, metadata безtext/bytes, scope/expired epochs, dirty/current/original/history точны; malformed media/UTF8/duplicate keys/unknown fields/query/headers/CL/TE/bounds до dispatch, stream без CL/disconnect; gate busy/release и cancel/send ACK-loss; no-store и unique errors; health-only first import/app construction/OpenAPI inert; route/schema refs/old routes сохранены; fake/corrupt metadata/encoder error без содержания. Targeted+full bash scripts/check.sh+baseline/QA/result/local commit, затем E3 на Sol 6.1 High.
